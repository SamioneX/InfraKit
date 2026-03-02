"""Rich terminal output helpers."""

from __future__ import annotations

from typing import Any

from rich.table import Table

from infrakit.utils.logging import console


def print_plan_table(
    creates: list[tuple[str, str]],
    updates: list[tuple[str, str]],
    deletes: list[tuple[str, str]],
) -> None:
    """Print a Terraform-style plan summary table."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("symbol", style="bold", width=3)
    table.add_column("name")
    table.add_column("type", style="dim")
    table.add_column("action", style="dim")

    for name, rtype in creates:
        table.add_row("[green]+[/green]", name, f"({rtype})", "will be created")
    for name, rtype in updates:
        table.add_row("[yellow]~[/yellow]", name, f"({rtype})", "will be updated")
    for name, rtype in deletes:
        table.add_row("[red]-[/red]", name, f"({rtype})", "will be destroyed")

    console.print()
    console.print(table)
    console.print(
        f"\n  [bold]Plan:[/bold] "
        f"[green]{len(creates)} to create[/green], "
        f"[yellow]{len(updates)} to update[/yellow], "
        f"[red]{len(deletes)} to destroy[/red]."
    )
    console.print()


def print_drift_table(results: list[dict[str, Any]]) -> None:
    """Print drift detection results as a Rich table."""
    table = Table(title="Drift Report", show_lines=True)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Detail")

    for entry in results:
        status = entry["status"]
        if status == "OK":
            status_str = "[green]OK[/green]"
        elif status == "MISSING":
            status_str = "[red]MISSING[/red]"
        else:
            status_str = "[yellow]ERROR[/yellow]"
        table.add_row(entry["name"], entry["type"], status_str, entry.get("detail", ""))

    console.print()
    console.print(table)
    console.print()
