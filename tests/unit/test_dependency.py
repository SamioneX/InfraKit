"""Unit tests for core/dependency.py."""

from __future__ import annotations

import pytest

from infrakit.core.dependency import (
    CyclicDependencyError,
    build_dag,
    creation_order,
    destruction_order,
    extract_refs,
)


class TestExtractRefs:
    def test_no_refs(self) -> None:
        assert extract_refs({"type": "dynamodb", "hash_key": "id"}) == set()

    def test_single_ref_in_string(self) -> None:
        refs = extract_refs({"role": "!ref my_role.arn"})
        assert refs == {"my_role"}

    def test_ref_in_nested_dict(self) -> None:
        refs = extract_refs({"environment": {"TABLE": "!ref my_table.name"}})
        assert refs == {"my_table"}

    def test_multiple_refs(self) -> None:
        refs = extract_refs(
            {"role": "!ref role_a.arn", "env": {"TABLE": "!ref table_b.name"}}
        )
        assert refs == {"role_a", "table_b"}

    def test_ref_only_extracts_resource_name(self) -> None:
        refs = extract_refs({"url": "!ref resource.sub.attribute"})
        assert refs == {"resource"}


class TestCreationOrder:
    def _make_services(self, deps: dict[str, list[str]]) -> dict[str, dict[str, str]]:
        """Build a minimal fake services dict with !ref strings."""
        services: dict[str, dict[str, str]] = {}
        for name, depends_on in deps.items():
            entry: dict[str, str] = {"type": "dynamodb", "hash_key": "id"}
            for dep in depends_on:
                entry[f"ref_{dep}"] = f"!ref {dep}.arn"
            services[name] = entry
        return services

    def test_no_dependencies_any_order(self) -> None:
        services = self._make_services({"a": [], "b": [], "c": []})
        order = creation_order(services)
        assert set(order) == {"a", "b", "c"}

    def test_linear_chain(self) -> None:
        services = self._make_services({"a": [], "b": ["a"], "c": ["b"]})
        order = creation_order(services)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dependency(self) -> None:
        # c depends on a and b; b depends on a
        services = self._make_services({"a": [], "b": ["a"], "c": ["a", "b"]})
        order = creation_order(services)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_cyclic_dependency_raises(self) -> None:
        services = self._make_services({"a": ["b"], "b": ["a"]})
        with pytest.raises(CyclicDependencyError):
            creation_order(services)

    def test_undefined_ref_raises_value_error(self) -> None:
        services = self._make_services({"a": ["missing"]})
        with pytest.raises(ValueError, match="missing"):
            creation_order(services)

    def test_destruction_order_is_reverse(self) -> None:
        services = self._make_services({"a": [], "b": ["a"]})
        create = creation_order(services)
        destroy = destruction_order(services)
        assert destroy == list(reversed(create))
