"""Deployment engine — orchestrates deploy / destroy / plan.

The engine is the brain of InfraKit.  It:
1. Validates the config and resolves !ref dependency order.
2. Acquires a state lock.
3. Provisions resources in dependency order, saving state after each one.
4. On failure, rolls back resources created in the current run.
"""

from __future__ import annotations

import uuid
from typing import Any

from rich.console import Console

from infrakit.core.dependency import creation_order, destruction_order
from infrakit.core.session import AWSSession
from infrakit.providers.api_gateway import APIGatewayProvider
from infrakit.providers.base import ResourceProvider
from infrakit.providers.dynamodb import DynamoDBProvider
from infrakit.providers.iam import IAMProvider
from infrakit.providers.lambda_ import LambdaProvider
from infrakit.providers.s3 import S3Provider
from infrakit.schema.models import (
    APIGatewayResource,
    DynamoDBResource,
    IAMRoleResource,
    InfraKitConfig,
    LambdaResource,
    S3Resource,
)
from infrakit.state.backend import StateBackend
from infrakit.state.local import LocalStateBackend
from infrakit.utils.logging import get_logger
from infrakit.utils.output import print_plan_table

logger = get_logger(__name__)
console = Console()


def _make_provider(
    name: str,
    resource: Any,
    project: str,
    env: str,
    region: str,
) -> ResourceProvider:
    """Factory — returns the correct provider for *resource*."""
    if isinstance(resource, DynamoDBResource):
        return DynamoDBProvider(name, resource, project, env, region)
    if isinstance(resource, IAMRoleResource):
        return IAMProvider(name, resource, project, env, region)
    if isinstance(resource, LambdaResource):
        return LambdaProvider(name, resource, project, env, region)
    if isinstance(resource, APIGatewayResource):
        return APIGatewayProvider(name, resource, project, env, region)
    if isinstance(resource, S3Resource):
        return S3Provider(name, resource, project, env, region)
    raise NotImplementedError(f"No provider implemented for resource type: {type(resource)}")


def _make_state_backend(cfg: InfraKitConfig) -> StateBackend:
    state_cfg = cfg.state
    if state_cfg.backend == "local":
        return LocalStateBackend(state_cfg.path)
    raise NotImplementedError(
        "S3 state backend is Phase 3. Use backend: local for now."
    )


class Engine:
    """Orchestrates deploy, destroy, and plan for a given config."""

    def __init__(self, cfg: InfraKitConfig) -> None:
        self.cfg = cfg
        AWSSession.configure(region=cfg.region)
        self._backend = _make_state_backend(cfg)

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def plan(self) -> None:
        """Compute and display what would change without touching AWS."""
        state = self._backend.load()
        existing = set(state.get("resources", {}).keys())

        creates: list[tuple[str, str]] = []
        updates: list[tuple[str, str]] = []

        order = creation_order(self.cfg.services)
        for name in order:
            resource = self.cfg.services[name]
            rtype = resource.type
            if name in existing:
                updates.append((name, rtype))
            else:
                creates.append((name, rtype))

        deletes: list[tuple[str, str]] = []
        for name in existing:
            if name not in self.cfg.services:
                stored = state["resources"][name]
                deletes.append((name, stored.get("type", "unknown")))

        if not creates and not updates and not deletes:
            console.print("\n  [green]No changes needed. All resources are up to date.[/green]\n")
            return

        print_plan_table(creates, updates, deletes)

    def deploy(self, auto_approve: bool = False) -> None:
        """Provision all resources in dependency order.

        Idempotency: resources that already exist in state *and* in AWS are
        skipped — their stored outputs are reused.  Resources in state but
        missing from AWS are recreated (drift recovery).
        """
        run_id = str(uuid.uuid4())[:8]
        self._backend.lock(run_id)
        created_this_run: list[str] = []
        changes_made = 0

        try:
            state = self._backend.load()
            state.setdefault("resources", {})
            existing_state = state["resources"]
            accumulated_outputs: dict[str, dict[str, Any]] = {
                name: entry["outputs"]
                for name, entry in existing_state.items()
            }

            order = creation_order(self.cfg.services)

            for name in order:
                resource = self.cfg.services[name]
                provider = _make_provider(
                    name, resource, self.cfg.project, self.cfg.env, self.cfg.region
                )
                provider.resolve_refs(accumulated_outputs)

                rtype = resource.type

                if name in existing_state and provider.exists():
                    # Resource is tracked in state and confirmed live — no changes needed.
                    console.print(f"  [dim]=[/dim] {name} ({rtype}) — no changes")
                    outputs = accumulated_outputs[name]
                elif name in existing_state and not provider.exists():
                    # State says it exists but AWS disagrees — drift: recreate.
                    console.print(
                        f"  [yellow]![/yellow] {name} ({rtype}) — drift detected, recreating"
                    )
                    outputs = provider.create()
                    created_this_run.append(name)
                    changes_made += 1
                else:
                    console.print(f"  [green]+[/green] {name} ({rtype}) — creating")
                    outputs = provider.create()
                    created_this_run.append(name)
                    changes_made += 1

                accumulated_outputs[name] = outputs
                self._backend.set_resource(name, rtype, outputs)

        except Exception as exc:
            logger.error("Deployment failed: %s", exc)
            self._rollback(created_this_run)
            raise
        finally:
            self._backend.unlock(run_id)

        if changes_made == 0:
            console.print(
                "\n  [bold green]All resources up to date.[/bold green]\n"
            )
        else:
            console.print("\n  [bold green]Deploy complete.[/bold green]\n")

    def destroy(self, auto_approve: bool = False) -> None:
        """Tear down all resources tracked in state."""
        run_id = str(uuid.uuid4())[:8]
        self._backend.lock(run_id)

        try:
            state = self._backend.load()
            if not state.get("resources"):
                console.print("  No resources in state. Nothing to destroy.")
                return

            # Use destruction order based on what's in state (not current config)
            # so we can destroy even after renaming services.
            state_services = {
                name: self.cfg.services.get(name, entry)
                for name, entry in state["resources"].items()
            }

            try:
                order = destruction_order(
                    {k: v for k, v in self.cfg.services.items() if k in state_services}
                )
            except Exception:
                # If we can't compute order, just iterate state resources
                order = list(state_services.keys())

            for name in order:
                if name not in self.cfg.services:
                    logger.warning("Resource %s in state but not in config — skipping", name)
                    continue
                resource = self.cfg.services[name]
                provider = _make_provider(
                    name, resource, self.cfg.project, self.cfg.env, self.cfg.region
                )
                console.print(f"  [red]-[/red] {name} ({resource.type}) — destroying")
                provider.delete()
                self._backend.remove_resource(name)

        finally:
            self._backend.unlock(run_id)

        console.print("\n  [bold]Destroy complete.[/bold]\n")

    def status(self) -> None:
        """Print the current known state without calling AWS."""
        from rich.table import Table

        state = self._backend.load()
        resources = state.get("resources", {})

        if not resources:
            console.print("  No resources in state.")
            return

        table = Table(title="InfraKit State", show_lines=True)
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Outputs")

        for name, entry in resources.items():
            outputs_str = "\n".join(f"{k}: {v}" for k, v in entry.get("outputs", {}).items())
            table.add_row(name, entry.get("type", "?"), entry.get("status", "?"), outputs_str)

        console.print(table)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rollback(self, created_names: list[str]) -> None:
        """Delete resources created in the current (failed) run."""
        if not created_names:
            return
        console.print("\n  [red]Rolling back resources created this run…[/red]")
        for name in reversed(created_names):
            if name not in self.cfg.services:
                continue
            resource = self.cfg.services[name]
            try:
                provider = _make_provider(
                    name, resource, self.cfg.project, self.cfg.env, self.cfg.region
                )
                provider.delete()
                self._backend.remove_resource(name)
                console.print(f"  [red]-[/red] {name} rolled back")
            except Exception as exc:  # noqa: BLE001
                logger.error("Rollback failed for %s: %s", name, exc)
