"""``infrakit destroy`` command."""

from __future__ import annotations

import typer

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


def destroy(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", "-y", help="Skip confirmation prompt."
    ),
) -> None:
    """Tear down all resources tracked in state."""
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc

    if not auto_approve:
        typer.confirm(
            f"Destroy ALL resources in [{cfg.env}] {cfg.project}? This cannot be undone.",
            abort=True,
        )

    try:
        Engine(cfg).destroy(auto_approve=auto_approve)
    except Exception as exc:
        logger.error("Destroy failed: %s", exc)
        raise typer.Exit(1) from exc
