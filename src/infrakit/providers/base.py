"""Abstract base class for all InfraKit resource providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


class ResourceProvider(ABC):
    """Base class every provider must inherit from.

    A provider is responsible for a single resource type.  It knows how
    to create, delete, and check existence of that resource in AWS.

    Attributes:
        name:    The logical name from infrakit.yaml (e.g. "users_table").
        config:  The parsed resource config model (e.g. DynamoDBResource).
        project: The top-level project name (used for physical naming + tags).
        env:     The deployment environment ("dev", "staging", "prod").
    """

    def __init__(
        self,
        name: str,
        config: Any,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        self.name = name
        self.config = config
        self.project = project
        self.env = env
        self.region = region
        self.logger = get_logger(f"infrakit.providers.{name}")

    # ------------------------------------------------------------------
    # Physical naming
    # ------------------------------------------------------------------

    @property
    def physical_name(self) -> str:
        """AWS resource name: ``<project>-<env>-<logical-name>``."""
        return f"{self.project}-{self.env}-{self.name}"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def exists(self) -> bool:
        """Return True if the resource already exists in AWS."""

    @abstractmethod
    def create(self) -> dict[str, Any]:
        """Provision the resource and return its output attributes.

        Output attributes are persisted to state and used to resolve
        ``!ref`` values in other resources.

        Returns:
            A dict of string → string attributes (ARN, name, endpoint, …).
        """

    @abstractmethod
    def delete(self) -> None:
        """Tear down the resource.  Must be idempotent."""

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def update(self, previous_outputs: dict[str, Any]) -> dict[str, Any]:
        """Update an already-existing resource.

        Default implementation: delete then re-create.
        Override for in-place updates where the provider supports them.
        """
        self.logger.info("Replacing %s (delete → create)", self.name)
        self.delete()
        return self.create()

    def resolve_refs(self, state_outputs: dict[str, dict[str, Any]]) -> None:
        """Substitute ``!ref resource.attr`` placeholders in config fields.

        Called by the engine *after* dependency ordering, so all referenced
        resources have already been created and their outputs are in *state_outputs*.
        """
        import re

        _REF_RE = re.compile(r"^!ref\s+(\w[\w.-]*)$")

        for field_name, field_value in vars(self.config).items():
            if isinstance(field_value, str):
                m = _REF_RE.match(field_value)
                if m:
                    ref_path = m.group(1)
                    resolved = self._resolve_ref_path(ref_path, state_outputs)
                    setattr(self.config, field_name, resolved)
            elif isinstance(field_value, dict):
                new_dict = {}
                for k, v in field_value.items():
                    if isinstance(v, str):
                        m = _REF_RE.match(v)
                        if m:
                            ref_path = m.group(1)
                            v = self._resolve_ref_path(ref_path, state_outputs)
                    new_dict[k] = v
                setattr(self.config, field_name, new_dict)

    @staticmethod
    def _resolve_ref_path(ref_path: str, state_outputs: dict[str, dict[str, Any]]) -> str:
        """Resolve ``resource_name.attribute`` from accumulated state outputs."""
        parts = ref_path.split(".", 1)
        resource_name = parts[0]
        attr = parts[1] if len(parts) > 1 else "arn"
        outputs = state_outputs.get(resource_name, {})
        if attr not in outputs:
            raise KeyError(
                f"!ref '{ref_path}': resource '{resource_name}' has no attribute '{attr}'. "
                f"Available: {list(outputs.keys())}"
            )
        return str(outputs[attr])
