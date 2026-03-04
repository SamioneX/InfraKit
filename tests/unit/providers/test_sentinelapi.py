"""Unit tests for the SentinelAPI provider."""

from __future__ import annotations

from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from infrakit.providers.sentinelapi import SentinelAPIProvider
from infrakit.schema.models import SentinelAPIResource


def _make_provider(mode: str = "full") -> SentinelAPIProvider:
    cfg = SentinelAPIResource(
        type="sentinelapi",
        mode=mode,
        upstream_base_url="https://backend.example.com",
        jwt={"secret_key": "/myapp/jwt-secret"},
        optimize_for="cost",
    )
    return SentinelAPIProvider("sentinel", cfg, project="proj", env="dev")


class TestSentinelAPIProvider:
    def test_create_full_uses_sdk_and_maps_outputs(
        self, mocked_aws: None, monkeypatch: object
    ) -> None:
        provider = _make_provider(mode="full")
        captured: dict[str, object] = {}

        def fake_deploy_full(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "outputs": {
                    "AlbDnsName": "sentinel-alb.us-east-1.elb.amazonaws.com",
                    "EcsClusterName": "cluster-1",
                    "EcsServiceName": "service-1",
                    "RequestLogsTableName": "request-logs",
                    "TrafficAggregateTableName": "traffic-agg",
                    "BlocklistTableName": "blocklist",
                    "AnomalyDetectorFunctionName": "anomaly-fn",
                    "OptimizeFor": "cost",
                }
            }

        def fake_deploy_foundation(**kwargs: object) -> dict[str, object]:
            return {"outputs": {}}

        def fake_teardown_stack(**kwargs: object) -> dict[str, object]:
            return {"status": "deleted"}

        monkeypatch.setattr(
            SentinelAPIProvider,
            "_load_sdk",
            staticmethod(lambda: (fake_deploy_full, fake_deploy_foundation, fake_teardown_stack)),
        )

        outputs = provider.create()

        assert captured["stack_name"] == "proj-dev-sentinel-sentinel"
        assert outputs["alb_dns_name"] == "sentinel-alb.us-east-1.elb.amazonaws.com"
        assert outputs["service_url"] == "http://sentinel-alb.us-east-1.elb.amazonaws.com"
        assert outputs["request_logs_table_name"] == "request-logs"
        assert outputs["optimize_for_resolved"] == "cost"

    def test_create_foundation_calls_foundation(
        self, mocked_aws: None, monkeypatch: object
    ) -> None:
        provider = _make_provider(mode="foundation")
        called: dict[str, bool] = {"foundation": False}

        def fake_deploy_full(**kwargs: object) -> dict[str, object]:
            return {"outputs": {}}

        def fake_deploy_foundation(**kwargs: object) -> dict[str, object]:
            called["foundation"] = True
            return {"outputs": {"OptimizeFor": "cost"}}

        def fake_teardown_stack(**kwargs: object) -> dict[str, object]:
            return {"status": "deleted"}

        monkeypatch.setattr(
            SentinelAPIProvider,
            "_load_sdk",
            staticmethod(lambda: (fake_deploy_full, fake_deploy_foundation, fake_teardown_stack)),
        )

        provider.create()
        assert called["foundation"] is True

    def test_delete_calls_sdk_teardown(self, mocked_aws: None, monkeypatch: object) -> None:
        provider = _make_provider(mode="full")
        called: dict[str, bool] = {"teardown": False}

        def fake_deploy_full(**kwargs: object) -> dict[str, object]:
            return {"outputs": {}}

        def fake_deploy_foundation(**kwargs: object) -> dict[str, object]:
            return {"outputs": {}}

        def fake_teardown_stack(**kwargs: object) -> dict[str, object]:
            called["teardown"] = True
            assert kwargs["stack_name"] == "proj-dev-sentinel-sentinel"
            return {"status": "deleted"}

        monkeypatch.setattr(
            SentinelAPIProvider,
            "_load_sdk",
            staticmethod(lambda: (fake_deploy_full, fake_deploy_foundation, fake_teardown_stack)),
        )

        provider.delete()
        assert called["teardown"] is True

    def test_exists_false_when_stack_missing(self, mocked_aws: None) -> None:
        provider = _make_provider(mode="full")
        provider._cfn = MagicMock()
        provider._cfn.describe_stacks.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationError",
                    "Message": "Stack with id proj-dev-sentinel-sentinel does not exist",
                }
            },
            "DescribeStacks",
        )
        assert provider.exists() is False

    def test_sdk_config_payload_uses_optional_overrides(self, mocked_aws: None) -> None:
        cfg = SentinelAPIResource(
            type="sentinelapi",
            mode="full",
            upstream_base_url="https://backend.example.com",
            jwt={"jwks_url": "https://idp.example.com/.well-known/jwks.json", "algorithm": "RS256"},
            optimize_for="performance",
            fargate={"cpu": 1024, "memory_mib": 2048, "desired_count": 2},
            rate_limit={"capacity": 300, "refill_rate": 5.0},
            anomaly={"threshold": 5.0, "min_requests": 60, "auto_block": True},
            observability={"log_retention_days": 30, "request_timeout_seconds": 8},
            gateway_image_repository="public.ecr.aws/n6a2e6z3/sentinel-api-gateway",
            gateway_image_tag="1.0.6",
        )
        provider = SentinelAPIProvider("sentinel", cfg, project="proj", env="prod")
        payload = provider._sdk_config_payload

        assert payload["UPSTREAM_BASE_URL"] == "https://backend.example.com"
        assert payload["JWT_JWKS_URL"] == "https://idp.example.com/.well-known/jwks.json"
        assert payload["JWT_ALGORITHM"] == "RS256"
        assert payload["OPTIMIZE_FOR"] == "performance"
        assert payload["FARGATE_CPU"] == "1024"
        assert payload["RATE_LIMIT_REFILL_RATE"] == "5.0"
        assert payload["ANOMALY_AUTO_BLOCK"] == "true"
        assert payload["LOG_RETENTION_DAYS"] == "30"
