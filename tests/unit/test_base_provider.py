"""Unit tests for providers/base.py — ref resolution and naming."""

from __future__ import annotations

import pytest

from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import DynamoDBResource


class _ConcreteProvider(ResourceProvider):
    """Minimal concrete subclass for testing the abstract base."""

    def exists(self) -> bool:
        return False

    def create(self) -> dict[str, object]:
        return {}

    def delete(self) -> None:
        pass


@pytest.fixture()
def provider() -> _ConcreteProvider:
    cfg = DynamoDBResource(type="dynamodb", hash_key="id")
    return _ConcreteProvider("my_res", cfg, project="proj", env="dev")


class TestResourceProvider:
    def test_physical_name(self, provider: _ConcreteProvider) -> None:
        assert provider.physical_name == "proj-dev-my_res"

    def test_resolve_refs_substitutes_string(self, provider: _ConcreteProvider) -> None:
        provider.config.hash_key = "!ref other_res.name"
        state_outputs = {"other_res": {"name": "resolved-table-name"}}
        provider.resolve_refs(state_outputs)
        assert provider.config.hash_key == "resolved-table-name"

    def test_resolve_refs_leaves_non_ref_strings_unchanged(
        self, provider: _ConcreteProvider
    ) -> None:
        provider.config.hash_key = "plain-string"
        provider.resolve_refs({})
        assert provider.config.hash_key == "plain-string"

    def test_resolve_refs_dict_values(self, provider: _ConcreteProvider) -> None:
        from infrakit.providers.base import ResourceProvider
        from infrakit.schema.models import LambdaResource

        class _LambdaLike(ResourceProvider):
            def exists(self) -> bool:
                return False

            def create(self) -> dict[str, object]:
                return {}

            def delete(self) -> None:
                pass

        cfg = LambdaResource(
            type="lambda",
            handler="h.handler",
            environment={"TABLE": "!ref my_table.name"},
        )
        p = _LambdaLike("fn", cfg, project="proj", env="dev")
        p.resolve_refs({"my_table": {"name": "prod-table"}})
        assert p.config.environment["TABLE"] == "prod-table"

    def test_resolve_ref_path_missing_resource_raises(self) -> None:
        with pytest.raises(KeyError, match="no attribute"):
            ResourceProvider._resolve_ref_path("nonexistent.arn", {})

    def test_resolve_ref_path_missing_attr_raises(self) -> None:
        with pytest.raises(KeyError, match="no attribute"):
            ResourceProvider._resolve_ref_path("res.missing_attr", {"res": {"name": "x"}})

    def test_update_default_deletes_then_recreates(self, provider: _ConcreteProvider) -> None:
        """Default update() calls delete() then create() — exercising the base implementation."""
        calls: list[str] = []
        original_delete = provider.delete
        original_create = provider.create

        def _delete() -> None:
            calls.append("delete")
            original_delete()

        def _create() -> dict[str, object]:
            calls.append("create")
            return original_create()

        provider.delete = _delete  # type: ignore[method-assign]
        provider.create = _create  # type: ignore[method-assign]

        provider.update({})
        assert calls == ["delete", "create"]
