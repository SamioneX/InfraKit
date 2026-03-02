"""ECS Fargate service provider."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import ECSFargateResource
from infrakit.utils.tags import standard_tags, to_boto3_tags


class ECSFargateProvider(ResourceProvider):
    config: ECSFargateResource

    def __init__(
        self,
        name: str,
        config: ECSFargateResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._ecs = AWSSession.client("ecs", region_name=region)
        self._ec2 = AWSSession.client("ec2", region_name=region)

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    @property
    def _cluster_name(self) -> str:
        return f"{self.project}-{self.env}"

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            resp = self._ecs.describe_services(
                cluster=self._cluster_name,
                services=[self.physical_name],
            )
            services = resp.get("services", [])
            if not services:
                return False
            return str(services[0].get("status", "")) != "INACTIVE"
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ClusterNotFoundException", "ServiceNotFoundException"):
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        cluster_name = self._cluster_name

        # Ensure cluster exists (create_cluster is idempotent)
        self._ecs.create_cluster(clusterName=cluster_name)

        vpc_id, subnet_ids = self._get_default_vpc()
        sg_id = self._create_security_group(vpc_id, cfg.port)

        # Register task definition
        container_def: dict[str, Any] = {
            "name": self.physical_name,
            "image": cfg.image,
            "portMappings": [{"containerPort": cfg.port, "protocol": "tcp"}],
            "environment": [{"name": k, "value": v} for k, v in cfg.environment.items()],
            "essential": True,
        }

        task_kwargs: dict[str, Any] = {
            "family": self.physical_name,
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": str(cfg.cpu),
            "memory": str(cfg.memory_mb),
            "containerDefinitions": [container_def],
        }
        if cfg.task_role:
            task_kwargs["executionRoleArn"] = cfg.task_role
            task_kwargs["taskRoleArn"] = cfg.task_role

        self._ecs.register_task_definition(**task_kwargs)

        # Build service kwargs
        service_kwargs: dict[str, Any] = {
            "cluster": cluster_name,
            "serviceName": self.physical_name,
            "taskDefinition": self.physical_name,
            "launchType": "FARGATE",
            "desiredCount": cfg.desired_count,
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": subnet_ids,
                    "securityGroups": [sg_id],
                    "assignPublicIp": "ENABLED",
                }
            },
        }

        if cfg.load_balancer:
            service_kwargs["loadBalancers"] = [
                {
                    "targetGroupArn": cfg.load_balancer,
                    "containerName": self.physical_name,
                    "containerPort": cfg.port,
                }
            ]

        # IAM is eventually consistent — retry if the execution role hasn't propagated yet
        for attempt in range(6):
            try:
                resp = self._ecs.create_service(**service_kwargs)
                break
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                msg = exc.response["Error"]["Message"]
                if code == "InvalidParameterException" and (
                    "service linked role" in msg.lower() or "cannot be assumed" in msg.lower()
                ):
                    if attempt < 5:
                        wait = 10 * (attempt + 1)
                        self.logger.debug(
                            "IAM role not yet propagated, retrying in %ss (attempt %s/5)",
                            wait,
                            attempt + 1,
                        )
                        time.sleep(wait)  # pragma: no cover
                    else:
                        raise
                else:
                    raise
        else:
            raise RuntimeError(  # pragma: no cover
                f"ECS service {self.physical_name} failed to create after 6 attempts "
                "(IAM propagation timeout)"
            )
        service = resp["service"]
        service_arn: str = service["serviceArn"]

        # Tag the service
        tags = to_boto3_tags(standard_tags(self.project, self.env))
        ecs_tags = [{"key": t["Key"], "value": t["Value"]} for t in tags]
        with contextlib.suppress(ClientError):
            self._ecs.tag_resource(resourceArn=service_arn, tags=ecs_tags)

        self.logger.info("Created ECS Fargate service: %s", self.physical_name)
        return {
            "name": self.physical_name,
            "arn": service_arn,
            "cluster": cluster_name,
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("ECS service %s already absent.", self.physical_name)
            return

        cluster_name = self._cluster_name

        # Scale to 0 before deleting
        with contextlib.suppress(ClientError):
            self._ecs.update_service(
                cluster=cluster_name,
                service=self.physical_name,
                desiredCount=0,
            )

        try:
            self._ecs.delete_service(
                cluster=cluster_name,
                service=self.physical_name,
                force=True,
            )
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in ("ServiceNotFoundException", "ClusterNotFoundException"):
                raise

        # Deregister task definitions for this family
        self._deregister_task_definitions()

        self.logger.info("Deleted ECS Fargate service: %s", self.physical_name)

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
        sg_name = f"{self.physical_name}-ecs-sg"
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
            Description=f"InfraKit ECS SG for {self.physical_name}",
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

    def _deregister_task_definitions(self) -> None:
        """Deregister all task definition revisions for this service's family."""
        with contextlib.suppress(ClientError):
            paginator = self._ecs.get_paginator("list_task_definitions")
            for page in paginator.paginate(familyPrefix=self.physical_name, status="ACTIVE"):
                for arn in page.get("taskDefinitionArns", []):
                    with contextlib.suppress(ClientError):
                        self._ecs.deregister_task_definition(taskDefinition=arn)
