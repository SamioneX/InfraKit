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
from infrakit.providers.alb import ALBProvider
from infrakit.providers.api_gateway import APIGatewayProvider
from infrakit.providers.base import ResourceProvider
from infrakit.providers.dns import DNSProvider
from infrakit.providers.dynamodb import DynamoDBProvider
from infrakit.providers.ecs import ECSFargateProvider
from infrakit.providers.elasticache import ElastiCacheProvider
from infrakit.providers.iam import IAMProvider
from infrakit.providers.lambda_ import LambdaProvider
from infrakit.providers.s3 import S3Provider
from infrakit.schema.models import (
    ALBResource,
    APIGatewayResource,
    DNSResource,
    DynamoDBResource,
    ECSFargateResource,
    ElastiCacheResource,
    IAMRoleResource,
    InfraKitConfig,
    LambdaResource,
    LocalStateConfig,
    S3Resource,
    S3StateConfig,
)
from infrakit.state.backend import StateBackend
from infrakit.state.local import LocalStateBackend
from infrakit.state.s3 import S3StateBackend
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
    if isinstance(resource, DNSResource):
        return DNSProvider(name, resource, project, env, region)
    if isinstance(resource, IAMRoleResource):
        return IAMProvider(name, resource, project, env, region)
    if isinstance(resource, LambdaResource):
        return LambdaProvider(name, resource, project, env, region)
    if isinstance(resource, APIGatewayResource):
        return APIGatewayProvider(name, resource, project, env, region)
    if isinstance(resource, S3Resource):
        return S3Provider(name, resource, project, env, region)
    if isinstance(resource, ECSFargateResource):
        return ECSFargateProvider(name, resource, project, env, region)
    if isinstance(resource, ElastiCacheResource):
        return ElastiCacheProvider(name, resource, project, env, region)
    if isinstance(resource, ALBResource):
        return ALBProvider(name, resource, project, env, region)
    raise NotImplementedError(f"No provider implemented for resource type: {type(resource)}")


def _make_state_backend(cfg: InfraKitConfig) -> StateBackend:
    state_cfg = cfg.state
    if isinstance(state_cfg, LocalStateConfig):
        return LocalStateBackend(state_cfg.path)
    if isinstance(state_cfg, S3StateConfig):
        return S3StateBackend(
            bucket=state_cfg.bucket,
            lock_table=state_cfg.lock_table,
            key_prefix=state_cfg.key_prefix,
            project=cfg.project,
            env=cfg.env,
            region=cfg.region,
        )
    raise NotImplementedError(f"Unknown state backend: {state_cfg.backend}")


class Engine:
    """Orchestrates deploy, destroy, and plan for a given config."""

    def __init__(self, cfg: InfraKitConfig) -> None:
        self.cfg = cfg
        AWSSession.configure(region=cfg.region)
        self._backend = _make_state_backend(cfg)

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def plan_data(self) -> dict[str, Any]:
        """Return the plan as a structured dict (single source of truth for plan logic).

        Used by both the human-readable table output and --json output.
        """
        state = self._backend.load()
        existing = set(state.get("resources", {}).keys())
        order = creation_order(self.cfg.services)
        creates = [
            {"name": n, "type": self.cfg.services[n].type} for n in order if n not in existing
        ]
        deletes = [
            {"name": n, "type": state["resources"][n].get("type", "unknown")}
            for n in existing
            if n not in self.cfg.services
        ]
        return {
            "creates": creates,
            "deletes": deletes,
            "summary": f"{len(creates)} to create, {len(deletes)} to delete",
            "has_changes": bool(creates or deletes),
        }

    def plan(self) -> None:
        """Compute and display what would change without touching AWS.

        Creates: resources in config but not yet in state.
        Deletes: resources in state but removed from config.
        (Config-level updates are not yet detected — use ``infrakit drift`` for that.)
        """
        data = self.plan_data()
        if not data["has_changes"]:
            console.print("\n  [green]No changes needed. All resources are up to date.[/green]\n")
            return
        creates = [(c["name"], c["type"]) for c in data["creates"]]
        deletes = [(d["name"], d["type"]) for d in data["deletes"]]
        print_plan_table(creates, [], deletes)

    def drift(self) -> list[dict[str, Any]]:
        """Compare state against live AWS and report out-of-band changes.

        For each resource tracked in state (that is still in config), calls the
        provider's ``exists()`` and classifies the result as OK or MISSING.
        Resources removed from config are skipped — ``plan()`` handles those.
        No state lock is acquired because drift is read-only.
        """
        state = self._backend.load()
        resources = state.get("resources", {})
        if not resources:
            console.print("\n  [yellow]No resources in state. Nothing to check.[/yellow]\n")
            return []

        # Build accumulated_outputs from stored state so resolve_refs() works.
        # All providers' exists() only need physical_name (from name/project/env),
        # but resolving refs keeps the call consistent with how deploy() works.
        accumulated_outputs: dict[str, dict[str, Any]] = {
            name: entry.get("outputs", {}) for name, entry in resources.items()
        }

        results: list[dict[str, Any]] = []
        for name, entry in resources.items():
            rtype = entry.get("type", "unknown")
            resource_cfg = self.cfg.services.get(name)
            if resource_cfg is None:
                # Resource in state but removed from config — plan() handles it.
                logger.debug("Drift: %s in state but not in config — skipped", name)
                continue
            try:
                provider = _make_provider(
                    name, resource_cfg, self.cfg.project, self.cfg.env, self.cfg.region
                )
                provider.resolve_refs(accumulated_outputs)
                if provider.exists():
                    results.append({"name": name, "type": rtype, "status": "OK", "detail": ""})
                else:
                    results.append(
                        {
                            "name": name,
                            "type": rtype,
                            "status": "MISSING",
                            "detail": "Resource deleted out-of-band.",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "name": name,
                        "type": rtype,
                        "status": "ERROR",
                        "detail": str(exc),
                    }
                )

        return results

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
                name: entry["outputs"] for name, entry in existing_state.items()
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
            console.print("\n  [bold green]All resources up to date.[/bold green]\n")
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
        failed_rollback: list[str] = []

        for name in reversed(created_names):
            if name not in self.cfg.services:
                continue
            resource = self.cfg.services[name]
            # Mark as "failed" before attempting delete so a crash during rollback
            # leaves an observable record in state.
            try:
                self._backend.set_resource(name, resource.type, {}, status="failed")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not mark %s as failed in state: %s", name, exc)
            try:
                provider = _make_provider(
                    name, resource, self.cfg.project, self.cfg.env, self.cfg.region
                )
                provider.delete()
                self._backend.remove_resource(name)
                console.print(f"  [red]-[/red] {name} rolled back")
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Rollback failed for %s: %s — resource may need manual cleanup", name, exc
                )
                failed_rollback.append(name)

        if failed_rollback:
            console.print(
                f"\n  [red]WARNING: rollback incomplete for: {', '.join(failed_rollback)} "
                "— manual AWS cleanup may be required.[/red]"
            )
