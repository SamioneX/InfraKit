"""Dependency DAG resolver.

Reads resource configs for ``!ref`` values, builds a directed acyclic
graph (DAG), and returns resources in topological creation order.
Cyclic dependencies are caught here — before any AWS call is made.
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx

_REF_RE = re.compile(r"!ref\s+(\w[\w.-]*)")


class CyclicDependencyError(Exception):
    """Raised when the resource graph contains a cycle."""


def extract_refs(resource_dict: dict[str, Any]) -> set[str]:
    """Return the set of resource names referenced via ``!ref`` in *resource_dict*."""
    refs: set[str] = set()

    def _scan(value: Any) -> None:
        if isinstance(value, str):
            for m in _REF_RE.finditer(value):
                ref_path = m.group(1)
                resource_name = ref_path.split(".")[0]
                refs.add(resource_name)
        elif isinstance(value, dict):
            for v in value.values():
                _scan(v)
        elif isinstance(value, list):
            for item in value:
                _scan(item)

    _scan(resource_dict)
    return refs


def build_dag(services: dict[str, Any]) -> nx.DiGraph[str]:
    """Build a directed graph where an edge A→B means A depends on B.

    Args:
        services: The raw parsed service dict from the YAML (before Pydantic).
                  Each value is a dict (or already a Pydantic model with
                  model_dump()).

    Returns:
        A ``networkx.DiGraph`` with one node per service name.
    """
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(services.keys())

    for name, resource in services.items():
        raw = resource.model_dump() if hasattr(resource, "model_dump") else dict(resource)

        for dep in extract_refs(raw):
            if dep not in services:
                raise ValueError(
                    f"Resource '{name}' references '{dep}' via !ref, "
                    f"but '{dep}' is not defined in services."
                )
            graph.add_edge(name, dep)  # name depends on dep

    return graph


def creation_order(services: dict[str, Any]) -> list[str]:
    """Return service names in dependency-safe creation order.

    Resources with no dependencies come first.
    Raises ``CyclicDependencyError`` if the graph has cycles.
    """
    graph = build_dag(services)

    if not nx.is_directed_acyclic_graph(graph):
        cycles = list(nx.simple_cycles(graph))
        cycle_str = " → ".join(cycles[0]) if cycles else "unknown"
        raise CyclicDependencyError(
            f"Circular dependency detected: {cycle_str}"
        )

    # Reverse topological sort: dependencies come before dependents
    return list(reversed(list(nx.topological_sort(graph))))


def destruction_order(services: dict[str, Any]) -> list[str]:
    """Return service names in dependency-safe destruction order (reverse of creation)."""
    return list(reversed(creation_order(services)))
