"""``infrakit plan`` command."""

from __future__ import annotations

import json

import typer

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


def plan(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Output plan as JSON to stdout."),
) -> None:
    """Show what would change without making any AWS calls."""
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc

    engine = Engine(cfg)
    if json_output:
        typer.echo(json.dumps(engine.plan_data(), indent=2))
    else:
        engine.plan()
