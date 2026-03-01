"""Unit tests for the IAM provider."""

from __future__ import annotations

import pytest

from infrakit.providers.iam import IAMProvider
from infrakit.schema.models import IAMRoleResource


@pytest.fixture()
def provider(mocked_aws: None) -> IAMProvider:
    cfg = IAMRoleResource(
        type="iam-role",
        assumed_by="lambda.amazonaws.com",
        policies=[],  # moto doesn't have AWS managed policies pre-seeded
    )
    return IAMProvider("api_role", cfg, project="myapp", env="dev")


class TestIAMProvider:
    def test_physical_name(self, provider: IAMProvider) -> None:
        assert provider.physical_name == "myapp-dev-api_role"

    def test_exists_false_initially(self, provider: IAMProvider) -> None:
        assert provider.exists() is False

    def test_create_returns_arn_and_name(self, provider: IAMProvider) -> None:
        outputs = provider.create()
        assert "arn" in outputs
        assert "name" in outputs
        assert outputs["name"] == "myapp-dev-api_role"
        assert "arn:aws:iam::" in outputs["arn"]

    def test_exists_true_after_create(self, provider: IAMProvider) -> None:
        provider.create()
        assert provider.exists() is True

    def test_delete_removes_role(self, provider: IAMProvider) -> None:
        provider.create()
        provider.delete()
        assert provider.exists() is False

    def test_delete_when_not_exists_is_safe(self, provider: IAMProvider) -> None:
        provider.delete()  # should not raise

    def test_inline_policy(self, mocked_aws: None) -> None:
        cfg = IAMRoleResource(
            type="iam-role",
            assumed_by="lambda.amazonaws.com",
            policies=[
                {
                    "inline": {
                        "dynamodb:GetItem,dynamodb:PutItem": "arn:aws:dynamodb:us-east-1:123456789012:table/my-table"
                    }
                }
            ],
        )
        p = IAMProvider("inline_role", cfg, project="proj", env="dev")
        outputs = p.create()
        assert "arn" in outputs
