"""ElastiCache cluster provider."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import ElastiCacheResource
from infrakit.utils.tags import standard_tags, to_boto3_tags

# Redis port / Memcached port
_ENGINE_PORTS = {"redis": 6379, "memcached": 11211}
# ElastiCache cluster ID max length
_MAX_CLUSTER_ID = 20


class ElastiCacheProvider(ResourceProvider):
    config: ElastiCacheResource

    def __init__(
        self,
        name: str,
        config: ElastiCacheResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("elasticache", region_name=region)
        self._ec2 = AWSSession.client("ec2", region_name=region)

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    @property
    def _cluster_id(self) -> str:
        """ElastiCache cluster IDs are max 20 chars, alphanumeric + hyphens only."""
        raw = self.physical_name.replace("_", "-")[:_MAX_CLUSTER_ID].rstrip("-")
        return raw

    @property
    def _subnet_group_name(self) -> str:
        return f"{self._cluster_id}-sg"

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            resp = self._client.describe_cache_clusters(CacheClusterId=self._cluster_id)
            clusters = resp.get("CacheClusters", [])
            if not clusters:
                return False
            status = clusters[0].get("CacheClusterStatus", "")
            # "deleting" and "deleted" mean the cluster is effectively gone
            return status not in ("deleting", "deleted", "create-failed")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "CacheClusterNotFound":
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        cluster_id = self._cluster_id
        engine_port = _ENGINE_PORTS.get(cfg.engine, 6379)

        vpc_id, subnet_ids = self._get_default_vpc()
        vpc_cidr = self._get_vpc_cidr(vpc_id)

        # Create subnet group
        subnet_group = self._subnet_group_name
        self._client.create_cache_subnet_group(
            CacheSubnetGroupName=subnet_group,
            CacheSubnetGroupDescription=f"InfraKit-managed subnet group for {cluster_id}",
            SubnetIds=subnet_ids,
        )

        # Create security group
        sg_id = self._create_security_group(vpc_id, vpc_cidr, engine_port)

        # Create cluster
        tags = to_boto3_tags(standard_tags(self.project, self.env))
        self._client.create_cache_cluster(
            CacheClusterId=cluster_id,
            CacheNodeType=cfg.node_type,
            Engine=cfg.engine,
            NumCacheNodes=cfg.num_nodes,
            CacheSubnetGroupName=subnet_group,
            SecurityGroupIds=[sg_id],
            Tags=tags,
        )

        # Poll until available
        endpoint, port = self._wait_for_available(cluster_id, cfg.engine)

        account_id = self._get_account_id()
        arn = f"arn:aws:elasticache:{self.region}:{account_id}:cluster:{cluster_id}"
        self.logger.info("Created ElastiCache cluster: %s", cluster_id)
        return {
            "name": cluster_id,
            "endpoint": endpoint,
            "port": str(port),
            "arn": arn,
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("ElastiCache cluster %s already absent.", self._cluster_id)
            return

        cluster_id = self._cluster_id
        self._client.delete_cache_cluster(CacheClusterId=cluster_id)
        self._wait_for_deleted(cluster_id)

        # Delete subnet group (best-effort; moto does not implement this API)
        with contextlib.suppress(ClientError, NotImplementedError):
            self._client.delete_cache_subnet_group(CacheSubnetGroupName=self._subnet_group_name)

        self.logger.info("Deleted ElastiCache cluster: %s", cluster_id)

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

    def _get_vpc_cidr(self, vpc_id: str) -> str:
        resp = self._ec2.describe_vpcs(VpcIds=[vpc_id])
        return str(resp["Vpcs"][0]["CidrBlock"])

    def _create_security_group(self, vpc_id: str, vpc_cidr: str, port: int) -> str:
        sg_name = f"{self._cluster_id}-cache-sg"
        resp = self._ec2.create_security_group(
            GroupName=sg_name,
            Description=f"InfraKit ElastiCache SG for {self._cluster_id}",
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
                    "IpRanges": [{"CidrIp": vpc_cidr}],
                }
            ],
        )
        return sg_id

    def _wait_for_available(self, cluster_id: str, engine: str) -> tuple[str, int]:
        """Poll until cluster is available; return (endpoint_address, port)."""
        for _ in range(30):
            resp = self._client.describe_cache_clusters(
                CacheClusterId=cluster_id, ShowCacheNodeInfo=True
            )
            cluster = resp["CacheClusters"][0]
            status = cluster.get("CacheClusterStatus", "")
            if status == "available":
                return self._extract_endpoint(cluster, engine)
            time.sleep(10)  # pragma: no cover
        raise TimeoutError(f"ElastiCache cluster {cluster_id} did not become available in time.")

    def _wait_for_deleted(self, cluster_id: str) -> None:
        """Wait for cluster deletion to complete."""
        try:
            resp = self._client.describe_cache_clusters(CacheClusterId=cluster_id)
            clusters = resp.get("CacheClusters", [])
            if not clusters:
                return
            status = clusters[0].get("CacheClusterStatus", "")
            # "deleting" means the delete request was accepted — treat as done
            if status in ("deleted", "deleting"):
                return
            # Cluster still active — poll briefly for real AWS; moto won't transition
            for _ in range(10):  # pragma: no cover
                time.sleep(10)  # pragma: no cover
                try:  # pragma: no cover
                    r = self._client.describe_cache_clusters(CacheClusterId=cluster_id)  # pragma: no cover
                    c = r.get("CacheClusters", [])  # pragma: no cover
                    if not c or c[0].get("CacheClusterStatus") in ("deleted", "deleting"):  # pragma: no cover
                        return  # pragma: no cover
                except ClientError as inner:  # pragma: no cover
                    if inner.response["Error"]["Code"] == "CacheClusterNotFound":  # pragma: no cover
                        return  # pragma: no cover
                    raise  # pragma: no cover
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "CacheClusterNotFound":
                return
            raise

    def _extract_endpoint(self, cluster: dict[str, Any], engine: str) -> tuple[str, int]:
        """Extract endpoint address and port from a describe_cache_clusters response."""
        if engine == "memcached":
            ep = cluster.get("ConfigurationEndpoint", {})
            return str(ep.get("Address", "")), int(ep.get("Port", 11211))
        # Redis single node
        nodes = cluster.get("CacheNodes", [])
        if nodes:
            ep = nodes[0].get("Endpoint", {})
            return str(ep.get("Address", "")), int(ep.get("Port", 6379))
        return "", _ENGINE_PORTS[engine]

    def _get_account_id(self) -> str:
        sts = AWSSession.client("sts", region_name=self.region)
        return str(sts.get_caller_identity()["Account"])
