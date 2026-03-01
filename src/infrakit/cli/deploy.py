"""``infrakit deploy`` command."""

from __future__ import annotations

import typer

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


def deploy(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", "-y", help="Skip confirmation prompt."
    ),
) -> None:
    """Provision all resources defined in infrakit.yaml."""
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config, validate_refs

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc

    ref_errors = validate_refs(cfg)
    if ref_errors:
        logger.error("Config has invalid !ref values:\n%s", "\n".join(ref_errors))
        raise typer.Exit(1)

    if not auto_approve:
        typer.confirm(
            f"Deploy {len(cfg.services)} resource(s) to [{cfg.env}] {cfg.project}?",
            abort=True,
        )

    try:
        Engine(cfg).deploy(auto_approve=auto_approve)
    except Exception as exc:
        logger.error("Deploy failed: %s", exc)
        raise typer.Exit(1) from exc
