"""SentinelAPI resource provider backed by sentinel-api SDK deploy functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import SentinelAPIResource

SDKDeployFn = Callable[..., dict[str, Any]]
SDKTeardownFn = Callable[..., dict[str, Any]]


class SentinelAPIProvider(ResourceProvider):
    config: SentinelAPIResource

    def __init__(
        self,
        name: str,
        config: SentinelAPIResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._cfn = AWSSession.client("cloudformation", region_name=region)

    @property
    def _stack_name(self) -> str:
        # Keep stack names deterministic, lowercase, and under CFN's 128-char limit.
        return f"{self.project}-{self.env}-{self.name}-sentinel".replace("_", "-")[:128]

    def exists(self) -> bool:
        try:
            resp = self._cfn.describe_stacks(StackName=self._stack_name)
            stacks = resp.get("Stacks", [])
            if not stacks:
                return False
            status = str(stacks[0].get("StackStatus", ""))
            return status not in {"DELETE_COMPLETE", "DELETE_IN_PROGRESS"}
        except ClientError as exc:
            if "does not exist" in str(exc):
                return False
            raise

    def create(self) -> dict[str, Any]:
        deploy_full, deploy_foundation, _teardown = self._load_sdk()
        cfg = self.config

        deploy_kwargs: dict[str, Any] = {
            "stack_name": self._stack_name,
            "region": self.region,
            "config": self._sdk_config_payload,
        }
        if cfg.artifacts_bucket:
            deploy_kwargs["artifacts_bucket"] = cfg.artifacts_bucket
        if cfg.gateway_image_uri:
            deploy_kwargs["gateway_image_uri"] = cfg.gateway_image_uri
        deploy_kwargs["build_gateway_image"] = cfg.build_gateway_image

        result = (
            deploy_foundation(**deploy_kwargs)
            if cfg.mode == "foundation"
            else deploy_full(**deploy_kwargs)
        )
        outputs_raw = result.get("outputs", {})

        return self._normalize_outputs(outputs_raw)

    def delete(self) -> None:
        _deploy_full, _deploy_foundation, teardown_stack = self._load_sdk()
        teardown_stack(stack_name=self._stack_name, region=self.region)

    @property
    def _sdk_config_payload(self) -> dict[str, str]:
        cfg = self.config
        payload: dict[str, str] = {
            "UPSTREAM_BASE_URL": cfg.upstream_base_url,
            "OPTIMIZE_FOR": cfg.optimize_for,
            "JWT_ALGORITHM": cfg.jwt.algorithm,
        }

        if cfg.jwt.secret_key:
            payload["JWT_SECRET_KEY"] = cfg.jwt.secret_key
        if cfg.jwt.public_key:
            payload["JWT_PUBLIC_KEY"] = cfg.jwt.public_key
        if cfg.jwt.jwks_url:
            payload["JWT_JWKS_URL"] = cfg.jwt.jwks_url

        if cfg.fargate.cpu is not None:
            payload["FARGATE_CPU"] = str(cfg.fargate.cpu)
        if cfg.fargate.memory_mib is not None:
            payload["FARGATE_MEMORY_MIB"] = str(cfg.fargate.memory_mib)
        if cfg.fargate.desired_count is not None:
            payload["ECS_DESIRED_COUNT"] = str(cfg.fargate.desired_count)

        if cfg.rate_limit.capacity is not None:
            payload["RATE_LIMIT_CAPACITY"] = str(cfg.rate_limit.capacity)
        if cfg.rate_limit.refill_rate is not None:
            payload["RATE_LIMIT_REFILL_RATE"] = str(cfg.rate_limit.refill_rate)

        if cfg.anomaly.threshold is not None:
            payload["ANOMALY_THRESHOLD"] = str(cfg.anomaly.threshold)
        if cfg.anomaly.min_requests is not None:
            payload["ANOMALY_MIN_REQUESTS"] = str(cfg.anomaly.min_requests)
        if cfg.anomaly.auto_block is not None:
            payload["ANOMALY_AUTO_BLOCK"] = str(cfg.anomaly.auto_block).lower()
        if cfg.anomaly.auto_block_ttl_seconds is not None:
            payload["ANOMALY_AUTO_BLOCK_TTL_SECONDS"] = str(cfg.anomaly.auto_block_ttl_seconds)

        if cfg.observability.log_retention_days is not None:
            payload["LOG_RETENTION_DAYS"] = str(cfg.observability.log_retention_days)
        if cfg.observability.request_timeout_seconds is not None:
            payload["REQUEST_TIMEOUT_SECONDS"] = str(cfg.observability.request_timeout_seconds)

        if cfg.gateway_image_repository:
            payload["GATEWAY_IMAGE_REPOSITORY"] = cfg.gateway_image_repository
        if cfg.gateway_image_tag:
            payload["GATEWAY_IMAGE_TAG"] = cfg.gateway_image_tag

        return payload

    def _normalize_outputs(self, raw_outputs: dict[str, Any]) -> dict[str, Any]:
        alb_dns_name = str(raw_outputs.get("AlbDnsName", ""))
        if not alb_dns_name:
            # Foundation mode may not expose ALB outputs.
            alb_dns_name = str(raw_outputs.get("albDnsName", ""))

        optimize = str(raw_outputs.get("OptimizeFor", self.config.optimize_for))
        service_url = (
            str(raw_outputs.get("ServiceUrl", ""))
            or str(raw_outputs.get("serviceUrl", ""))
            or (f"http://{alb_dns_name}" if alb_dns_name else "")
        )

        outputs = {
            "stack_name": self._stack_name,
            "mode": self.config.mode,
            "alb_dns_name": alb_dns_name,
            "albDnsName": alb_dns_name,
            "service_url": service_url,
            "serviceUrl": service_url,
            "ecs_cluster_name": str(raw_outputs.get("EcsClusterName", "")),
            "ecsClusterName": str(raw_outputs.get("EcsClusterName", "")),
            "ecs_service_name": str(raw_outputs.get("EcsServiceName", "")),
            "ecsServiceName": str(raw_outputs.get("EcsServiceName", "")),
            "request_logs_table_name": str(raw_outputs.get("RequestLogsTableName", "")),
            "requestLogsTableName": str(raw_outputs.get("RequestLogsTableName", "")),
            "traffic_aggregate_table_name": str(raw_outputs.get("TrafficAggregateTableName", "")),
            "trafficAggregateTableName": str(raw_outputs.get("TrafficAggregateTableName", "")),
            "blocklist_table_name": str(raw_outputs.get("BlocklistTableName", "")),
            "blocklistTableName": str(raw_outputs.get("BlocklistTableName", "")),
            "anomaly_detector_function_name": str(
                raw_outputs.get("AnomalyDetectorFunctionName", "")
            ),
            "anomalyDetectorFunctionName": str(raw_outputs.get("AnomalyDetectorFunctionName", "")),
            "optimize_for_resolved": optimize,
            "optimizeForResolved": optimize,
        }
        return outputs

    @staticmethod
    def _load_sdk() -> tuple[SDKDeployFn, SDKDeployFn, SDKTeardownFn]:
        try:
            from sentinel_api import deploy_foundation, deploy_full, teardown_stack
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentinel-api package is required for type=sentinelapi. "
                'Install dependencies with `pip install -e ".[dev]"`.'
            ) from exc
        return deploy_full, deploy_foundation, teardown_stack
