"""Unit tests for the ALB provider."""

from __future__ import annotations

from infrakit.providers.alb import ALBProvider
from infrakit.schema.models import ALBResource


def _make_provider(mocked_aws: None) -> ALBProvider:
    cfg = ALBResource(
        type="alb",  # type: ignore[arg-type]
        port=80,
        health_check_path="/health",
        scheme="internet-facing",
    )
    return ALBProvider("web-alb", cfg, project="myapp", env="dev")


class TestALBProvider:
    def test_physical_name(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.physical_name == "myapp-dev-web-alb"

    def test_exists_false_when_no_alb(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        assert p.exists() is False

    def test_create_alb(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        outputs = p.create()
        assert "id" in outputs
        assert "endpoint" in outputs
        assert "arn" in outputs
        assert "hosted_zone_id" in outputs
        assert "target_group_arn" in outputs
        assert "elasticloadbalancing" in outputs["arn"]
        assert "arn:aws:elasticloadbalancing" in outputs["target_group_arn"]

    def test_exists_true_after_create(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        assert p.exists() is True

    def test_delete_alb(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.create()
        p.delete()
        assert p.exists() is False

    def test_delete_when_not_exists_is_safe(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        p.delete()  # should not raise

    def test_create_internal_alb(self, mocked_aws: None) -> None:
        cfg = ALBResource(
            type="alb",  # type: ignore[arg-type]
            port=8080,
            health_check_path="/ping",
            scheme="internal",
        )
        p = ALBProvider("internal-alb", cfg, project="proj", env="prod")
        outputs = p.create()
        assert outputs["endpoint"] != ""

    def test_outputs_target_group_arn_format(self, mocked_aws: None) -> None:
        p = _make_provider(mocked_aws)
        outputs = p.create()
        tg_arn = outputs["target_group_arn"]
        assert "targetgroup" in tg_arn
