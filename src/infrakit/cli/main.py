"""InfraKit CLI entrypoint.

All sub-commands are registered here.  The Typer ``app`` object is the
value pointed to by the ``[project.scripts]`` entrypoint in pyproject.toml.
"""

from __future__ import annotations

import typer

from infrakit.cli import deploy as _deploy_mod
from infrakit.cli import destroy as _destroy_mod
from infrakit.cli import status as _status_mod

app = typer.Typer(
    name="infrakit",
    help="Declarative AWS infrastructure from a single YAML file.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,  # let our logger handle it
)

app.command("deploy")(_deploy_mod.deploy)
app.command("destroy")(_destroy_mod.destroy)
app.command("status")(_status_mod.status)


@app.command("validate")
def validate(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
) -> None:
    """Validate infrakit.yaml without making any AWS calls."""
    from infrakit.schema.validator import ConfigError, load_config, validate_refs

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    ref_errors = validate_refs(cfg)
    if ref_errors:
        typer.echo("Config validation failed — invalid !ref values:", err=True)
        for err in ref_errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)

    typer.echo(f"✓ {config} is valid.")


@app.command("plan")
def plan(
    config: str = typer.Option("infrakit.yaml", "--config", "-c", help="Path to infrakit.yaml"),
) -> None:
    """Show what would change without making any AWS calls."""
    from infrakit.core.engine import Engine
    from infrakit.schema.validator import ConfigError, load_config

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    Engine(cfg).plan()
