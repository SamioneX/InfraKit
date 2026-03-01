"""Config loader convenience wrapper.

Re-exports ``load_config`` and ``ConfigError`` so callers can import
from a single, stable location::

    from infrakit.core.config import load_config, ConfigError
"""

from infrakit.schema.validator import ConfigError, load_config

__all__ = ["load_config", "ConfigError"]
