"""Unit tests for Engine.drift() and Engine.plan_data()."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from infrakit.core.engine import Engine
from infrakit.core.session import AWSSession
from infrakit.schema.validator import load_config


@pytest.fixture()
def drift_cfg(tmp_path: Path) -> Path:
    """2-resource config (DynamoDB + IAM role) with local state in tmp_path."""
    f = tmp_path / "infrakit.yaml"
    f.write_text(
        textwrap.dedent(f"""\
            project: drift-test
            region: us-east-1
            env: dev
            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json
            services:
              drift_table:
                type: dynamodb
                hash_key: id
                hash_key_type: S
              drift_role:
                type: iam-role
                assumed_by: lambda.amazonaws.com
                policies: []
        """),
        encoding="utf-8",
    )
    return f


class TestEngineDrift:
    def test_drift_empty_state(self, mocked_aws: None, drift_cfg: Path) -> None:
        """drift() returns [] when no resources are in state."""
        cfg = load_config(str(drift_cfg))
        results = Engine(cfg).drift()
        assert results == []

    def test_drift_all_ok(self, mocked_aws: None, drift_cfg: Path) -> None:
        """After a successful deploy, all resources report OK."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        results = engine.drift()
        assert len(results) == 2
        assert all(r["status"] == "OK" for r in results)

    def test_drift_detects_missing_dynamodb(self, mocked_aws: None, drift_cfg: Path) -> None:
        """Deleting a table out-of-band is reported as MISSING."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        # Simulate out-of-band deletion
        client = AWSSession.client("dynamodb")
        client.delete_table(TableName="drift-test-dev-drift_table")

        results = engine.drift()
        by_name = {r["name"]: r for r in results}
        assert by_name["drift_table"]["status"] == "MISSING"
        assert "out-of-band" in by_name["drift_table"]["detail"]
        assert by_name["drift_role"]["status"] == "OK"

    def test_drift_skips_resource_not_in_config(
        self, mocked_aws: None, drift_cfg: Path
    ) -> None:
        """Resources in state but removed from config are skipped (plan handles them)."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        # Inject a "stale" resource into state directly
        state = engine._backend.load()
        state["resources"]["stale_resource"] = {
            "type": "dynamodb",
            "outputs": {"name": "x", "arn": "arn:aws:dynamodb:::table/x"},
            "status": "created",
        }
        engine._backend.save(state)

        results = engine.drift()
        names = [r["name"] for r in results]
        assert "stale_resource" not in names
        assert len(results) == 2  # only the two resources still in config

    def test_drift_handles_provider_error(self, mocked_aws: None, drift_cfg: Path) -> None:
        """An exception from exists() is caught and reported as ERROR."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        from infrakit.providers.dynamodb import DynamoDBProvider

        with patch.object(
            DynamoDBProvider,
            "exists",
            side_effect=RuntimeError("connection timeout"),
        ):
            results = engine.drift()

        by_name = {r["name"]: r for r in results}
        assert by_name["drift_table"]["status"] == "ERROR"
        assert "connection timeout" in by_name["drift_table"]["detail"]


class TestEnginePlanData:
    def test_plan_data_empty_state(self, mocked_aws: None, drift_cfg: Path) -> None:
        """With no state, all services appear in creates."""
        cfg = load_config(str(drift_cfg))
        data = Engine(cfg).plan_data()
        assert data["has_changes"] is True
        assert len(data["creates"]) == 2
        assert data["deletes"] == []
        create_names = [c["name"] for c in data["creates"]]
        assert "drift_table" in create_names
        assert "drift_role" in create_names

    def test_plan_data_after_full_deploy(self, mocked_aws: None, drift_cfg: Path) -> None:
        """After a full deploy, plan_data reports no changes."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        data = engine.plan_data()
        assert data["has_changes"] is False
        assert data["creates"] == []
        assert data["deletes"] == []

    def test_plan_data_resource_removed_from_config(
        self, mocked_aws: None, drift_cfg: Path
    ) -> None:
        """A resource in state but not in config appears in deletes."""
        cfg = load_config(str(drift_cfg))
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        # Inject a stale entry into state
        state = engine._backend.load()
        state["resources"]["old_resource"] = {
            "type": "s3",
            "outputs": {"name": "old", "arn": "arn:aws:s3:::old"},
            "status": "created",
        }
        engine._backend.save(state)

        data = engine.plan_data()
        assert data["has_changes"] is True
        delete_names = [d["name"] for d in data["deletes"]]
        assert "old_resource" in delete_names

    def test_plan_data_summary_string(self, mocked_aws: None, drift_cfg: Path) -> None:
        """Summary string reflects create/delete counts."""
        cfg = load_config(str(drift_cfg))
        data = Engine(cfg).plan_data()
        assert "2 to create" in data["summary"]
        assert "0 to delete" in data["summary"]

    def test_plan_data_is_json_serializable(self, mocked_aws: None, drift_cfg: Path) -> None:
        """plan_data() output can be serialized to JSON without error."""
        cfg = load_config(str(drift_cfg))
        data = Engine(cfg).plan_data()
        serialized = json.dumps(data)
        parsed = json.loads(serialized)
        assert parsed["has_changes"] is True
