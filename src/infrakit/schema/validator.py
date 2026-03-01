"""YAML config loader and validator.

Usage::

    from infrakit.schema.validator import load_config
    cfg = load_config("infrakit.yaml")   # raises ConfigError on failure
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from infrakit.schema.models import InfraKitConfig
from infrakit.utils.logging import get_logger

logger = get_logger(__name__)

_REF_PATTERN = re.compile(r"^!ref\s+(\w[\w.-]*)$")


class ConfigError(Exception):
    """Raised when the infrakit.yaml file cannot be loaded or validated."""


# ---------------------------------------------------------------------------
# Custom YAML constructor for !ref tags
# ---------------------------------------------------------------------------


class _RefString(str):
    """A plain string that carries the raw !ref value so callers can detect it."""


def _ref_constructor(loader: yaml.Loader, node: yaml.ScalarNode) -> _RefString:
    value = loader.construct_scalar(node)
    return _RefString(f"!ref {value}")


def _make_loader() -> type[yaml.SafeLoader]:
    """Return a SafeLoader subclass with the !ref constructor registered."""

    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_constructor("!ref", _ref_constructor)
    return _Loader


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: str | Path = "infrakit.yaml") -> InfraKitConfig:
    """Read *path*, resolve !ref syntax, validate via Pydantic, return model.

    Raises:
        ConfigError: if the file doesn't exist, isn't valid YAML, or fails
                     Pydantic validation.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        raw_dict: Any = yaml.load(raw_text, Loader=_make_loader())  # noqa: S506
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {config_path}: {exc}") from exc

    if not isinstance(raw_dict, dict):
        raise ConfigError(f"{config_path} must be a YAML mapping at the top level.")

    try:
        cfg = InfraKitConfig.model_validate(raw_dict)
    except ValidationError as exc:
        # Convert Pydantic errors into a single readable message.
        lines = [f"Config validation failed ({config_path}):"]
        for err in exc.errors():
            loc = " → ".join(str(p) for p in err["loc"])
            lines.append(f"  {loc}: {err['msg']}")
        raise ConfigError("\n".join(lines)) from exc

    logger.debug("Config loaded: project=%s env=%s", cfg.project, cfg.env)
    return cfg


def validate_refs(cfg: InfraKitConfig) -> list[str]:
    """Return a list of validation errors for !ref values.

    Checks that every ``!ref resource.attribute`` points to a resource
    that exists in the config.  Does NOT check attribute names because
    those depend on what the provider actually outputs.
    """
    errors: list[str] = []
    service_names = set(cfg.services.keys())

    def _check_value(field_name: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        m = _REF_PATTERN.match(value)
        if not m:
            return
        ref_path = m.group(1)
        resource_name = ref_path.split(".")[0]
        if resource_name not in service_names:
            errors.append(
                f"  {field_name}: !ref '{ref_path}' — "
                f"resource '{resource_name}' does not exist in services."
            )

    for svc_name, svc in cfg.services.items():
        for field_name, field_value in svc.model_dump().items():
            if isinstance(field_value, dict):
                for k, v in field_value.items():
                    _check_value(f"{svc_name}.{field_name}.{k}", v)
            else:
                _check_value(f"{svc_name}.{field_name}", field_value)

    return errors
