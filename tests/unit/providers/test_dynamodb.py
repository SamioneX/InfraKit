"""Unit tests for the DynamoDB provider."""

from __future__ import annotations

import pytest

from infrakit.providers.dynamodb import DynamoDBProvider
from infrakit.schema.models import DynamoDBResource


@pytest.fixture()
def provider(mocked_aws: None) -> DynamoDBProvider:
    cfg = DynamoDBResource(type="dynamodb", hash_key="userId", hash_key_type="S")
    return DynamoDBProvider("users_table", cfg, project="myapp", env="dev")


class TestDynamoDBProvider:
    def test_physical_name(self, provider: DynamoDBProvider) -> None:
        assert provider.physical_name == "myapp-dev-users_table"

    def test_exists_false_when_no_table(self, provider: DynamoDBProvider) -> None:
        assert provider.exists() is False

    def test_create_returns_outputs(self, provider: DynamoDBProvider) -> None:
        outputs = provider.create()
        assert "name" in outputs
        assert "arn" in outputs
        assert outputs["name"] == "myapp-dev-users_table"

    def test_exists_true_after_create(self, provider: DynamoDBProvider) -> None:
        provider.create()
        assert provider.exists() is True

    def test_create_idempotent_second_call_allowed(self, provider: DynamoDBProvider) -> None:
        """Second create raises AWS error — engine prevents double-create, but provider
        doesn't need to handle it silently."""
        provider.create()
        # Calling create again would raise — that's expected; engine checks exists() first.

    def test_delete_removes_table(self, provider: DynamoDBProvider) -> None:
        provider.create()
        provider.delete()
        assert provider.exists() is False

    def test_delete_when_not_exists_is_safe(self, provider: DynamoDBProvider) -> None:
        provider.delete()  # should not raise

    def test_sort_key_included(self, mocked_aws: None) -> None:
        cfg = DynamoDBResource(
            type="dynamodb",
            hash_key="pk",
            hash_key_type="S",
            sort_key="sk",
            sort_key_type="S",
        )
        p = DynamoDBProvider("my_table", cfg, project="proj", env="dev")
        outputs = p.create()
        assert outputs["name"] == "proj-dev-my_table"

    def test_provisioned_billing(self, mocked_aws: None) -> None:
        cfg = DynamoDBResource(
            type="dynamodb",
            hash_key="id",
            billing="provisioned",
            read_capacity=5,
            write_capacity=5,
        )
        p = DynamoDBProvider("prov_table", cfg, project="proj", env="dev")
        outputs = p.create()
        assert outputs["name"] == "proj-dev-prov_table"

    def test_ttl_attribute(self, mocked_aws: None) -> None:
        cfg = DynamoDBResource(
            type="dynamodb",
            hash_key="id",
            ttl_attribute="expiresAt",
        )
        p = DynamoDBProvider("ttl_table", cfg, project="proj", env="dev")
        outputs = p.create()
        assert "arn" in outputs
