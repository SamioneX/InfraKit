"""Application Load Balancer provider."""

from __future__ import annotations

import time
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import ALBResource
from infrakit.utils.tags import standard_tags, to_boto3_tags

_MIN_SUBNETS = 2  # ALB requires at least 2 subnets in different AZs


class ALBProvider(ResourceProvider):
    config: ALBResource

    def __init__(
        self,
        name: str,
        config: ALBResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._elbv2 = AWSSession.client("elbv2", region_name=region)
        self._ec2 = AWSSession.client("ec2", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    @property
    def _alb_name(self) -> str:
        """ALB names only allow alphanumeric + hyphens (no underscores)."""
        return self.physical_name.replace("_", "-")

    def exists(self) -> bool:
        try:
            resp = self._elbv2.describe_load_balancers(Names=[self._alb_name])
            lbs = resp.get("LoadBalancers", [])
            return len(lbs) > 0
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("LoadBalancerNotFound", "ValidationError"):
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        tags = to_boto3_tags(standard_tags(self.project, self.env))

        vpc_id, subnet_ids = self._get_default_vpc()
        if len(subnet_ids) < _MIN_SUBNETS:
            raise RuntimeError(
                f"ALB requires at least {_MIN_SUBNETS} subnets (in different AZs). "
                f"Default VPC only has {len(subnet_ids)} subnet(s)."
            )

        sg_id = self._create_security_group(vpc_id, cfg.port)

        # Create ALB
        resp = self._elbv2.create_load_balancer(
            Name=self._alb_name,
            Subnets=subnet_ids,
            SecurityGroups=[sg_id],
            Scheme=cfg.scheme,
            Type="application",
            IpAddressType="ipv4",
            Tags=tags,
        )
        lb = resp["LoadBalancers"][0]
        alb_arn: str = lb["LoadBalancerArn"]
        dns_name: str = lb["DNSName"]
        alb_id = alb_arn.split("/")[-2]  # extract ID from ARN

        # Wait for ALB to be active
        self._wait_for_active(alb_arn)

        # Create target group (ip type for Fargate awsvpc networking)
        tg_name = f"{self._alb_name[:28]}-tg"  # TG name max 32 chars
        tg_resp = self._elbv2.create_target_group(
            Name=tg_name,
            Protocol="HTTP",
            Port=cfg.port,
            VpcId=vpc_id,
            TargetType="ip",
            HealthCheckPath=cfg.health_check_path,
            Tags=tags,
        )
        tg_arn: str = tg_resp["TargetGroups"][0]["TargetGroupArn"]

        # Create listener
        self._elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol="HTTP",
            Port=cfg.port,
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
            Tags=tags,
        )

        self.logger.info("Created ALB: %s", self._alb_name)
        return {
            "id": alb_id,
            "endpoint": dns_name,
            "arn": alb_arn,
            "hosted_zone_id": lb["CanonicalHostedZoneId"],
            "target_group_arn": tg_arn,
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("ALB %s already absent.", self._alb_name)
            return

        try:
            resp = self._elbv2.describe_load_balancers(Names=[self._alb_name])
            lb = resp["LoadBalancers"][0]
            alb_arn: str = lb["LoadBalancerArn"]
        except (ClientError, IndexError, KeyError):
            return

        # Delete all listeners
        try:
            listeners = self._elbv2.describe_listeners(LoadBalancerArn=alb_arn)
            for listener in listeners.get("Listeners", []):
                self._elbv2.delete_listener(ListenerArn=listener["ListenerArn"])
        except ClientError:
            pass

        # Delete the ALB
        try:
            self._elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
            self._wait_for_deleted(alb_arn)
        except ClientError:
            pass

        # Delete target groups associated with this ALB
        self._delete_target_group()

        self.logger.info("Deleted ALB: %s", self._alb_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_default_vpc(self) -> tuple[str, list[str]]:
        vpcs = self._ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
        if not vpcs["Vpcs"]:
            raise RuntimeError("No default VPC found in region. Create a default VPC first.")
        vpc_id: str = vpcs["Vpcs"][0]["VpcId"]
        subnets = self._ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        subnet_ids: list[str] = [s["SubnetId"] for s in subnets["Subnets"]]
        return vpc_id, subnet_ids

    def _create_security_group(self, vpc_id: str, port: int) -> str:
        sg_name = f"{self._alb_name}-alb-sg"
        # Reuse existing SG if a previous partial deploy left one behind
        existing = self._ec2.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [sg_name]},
                {"Name": "vpc-id", "Values": [vpc_id]},
            ]
        )
        if existing["SecurityGroups"]:
            return str(existing["SecurityGroups"][0]["GroupId"])
        resp = self._ec2.create_security_group(
            GroupName=sg_name,
            Description=f"InfraKit ALB SG for {self._alb_name}",
            VpcId=vpc_id,
        )
        sg_id: str = resp["GroupId"]
        self._ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                }
            ],
        )
        return sg_id

    def _wait_for_active(self, alb_arn: str) -> None:
        """Poll until ALB is active."""
        for _ in range(20):
            resp = self._elbv2.describe_load_balancers(LoadBalancerArns=[alb_arn])
            state = resp["LoadBalancers"][0]["State"]["Code"]
            if state == "active":
                return
            time.sleep(10)  # pragma: no cover
        raise TimeoutError(f"ALB {self.physical_name} did not become active in time.")

    def _wait_for_deleted(self, alb_arn: str) -> None:
        """Poll until ALB is deleted."""
        for _ in range(20):
            try:
                resp = self._elbv2.describe_load_balancers(LoadBalancerArns=[alb_arn])
                lb = resp["LoadBalancers"][0]
                if lb["State"]["Code"] == "deleted":
                    return
                time.sleep(10)  # pragma: no cover
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "LoadBalancerNotFound":
                    return
                raise

    def _delete_target_group(self) -> None:
        """Delete the target group created for this ALB."""
        tg_name = f"{self._alb_name[:28]}-tg"
        try:
            resp = self._elbv2.describe_target_groups(Names=[tg_name])
            for tg in resp.get("TargetGroups", []):
                self._elbv2.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
        except ClientError:
            pass
