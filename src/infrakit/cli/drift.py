"""``infrakit drift`` command."""

from __future__ import annotations

import json

import typer

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


def drift(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON to stdout."),
) -> None:
    """Compare state against live AWS and report out-of-band changes.

    Exits 0 when all tracked resources are present in AWS, 1 when drift is detected.
    """
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config
    from infrakit.utils.output import print_drift_table

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc

    results = Engine(cfg).drift()
    if not results:
        # Engine already printed "No resources in state" message.
        raise typer.Exit(0)

    missing = [r for r in results if r["status"] == "MISSING"]
    errors = [r for r in results if r["status"] == "ERROR"]
    has_drift = bool(missing or errors)

    if json_output:
        payload = {
            "project": cfg.project,
            "env": cfg.env,
            "resources": results,
            "summary": {
                "ok": len([r for r in results if r["status"] == "OK"]),
                "missing": len(missing),
                "error": len(errors),
                "total": len(results),
            },
            "has_drift": has_drift,
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        print_drift_table(results)
        if has_drift:
            typer.echo(
                f"  Drift detected: {len(missing)} missing, {len(errors)} error(s).\n"
                "  Run `infrakit deploy` to reconcile.\n"
            )
        else:
            typer.echo("  No drift detected. All resources match state.\n")

    raise typer.Exit(1 if has_drift else 0)
