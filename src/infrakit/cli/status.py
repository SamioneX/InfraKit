"""``infrakit status`` command."""

from __future__ import annotations

import typer

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


def status(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
) -> None:
    """Show current known state of all deployed resources."""
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc

    Engine(cfg).status()
