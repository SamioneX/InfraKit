"""Unit tests for deploy idempotency in the Engine."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from infrakit.cli.main import app
from infrakit.schema.validator import load_config

runner = CliRunner()


@pytest.fixture()
def simple_cfg(tmp_path: Path) -> Path:
    """A minimal single-DynamoDB-table config, using a local state path in tmp_path."""
    f = tmp_path / "infrakit.yaml"
    f.write_text(
        textwrap.dedent(f"""\
            project: idem-test
            region: us-east-1
            env: dev
            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json
            services:
              items_table:
                type: dynamodb
                hash_key: id
                hash_key_type: S
        """),
        encoding="utf-8",
    )
    return f


class TestDeployIdempotency:
    def test_second_deploy_shows_no_changes(
        self, mocked_aws: None, simple_cfg: Path
    ) -> None:
        """Running deploy twice on an unchanged config outputs 'up to date'."""
        # First deploy — creates the resource
        result1 = runner.invoke(
            app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
        )
        assert result1.exit_code == 0
        assert "creating" in result1.stdout.lower()

        # Second deploy — resource already exists, should be a no-op
        result2 = runner.invoke(
            app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
        )
        assert result2.exit_code == 0
        assert "up to date" in result2.stdout.lower()
        assert "creating" not in result2.stdout.lower()

    def test_second_deploy_does_not_call_create_again(
        self, mocked_aws: None, simple_cfg: Path
    ) -> None:
        """On a second deploy, the provider's create() must not be called."""
        from infrakit.providers.dynamodb import DynamoDBProvider

        # First deploy
        runner.invoke(app, ["deploy", "--config", str(simple_cfg), "--auto-approve"])

        original_create = DynamoDBProvider.create
        create_calls: list[str] = []

        def tracking_create(self: DynamoDBProvider) -> dict:  # type: ignore[override]
            create_calls.append(self.name)
            return original_create(self)

        with patch.object(DynamoDBProvider, "create", tracking_create):
            result = runner.invoke(
                app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
            )

        assert result.exit_code == 0
        assert create_calls == [], f"create() was unexpectedly called for: {create_calls}"

    def test_drift_recovery_recreates_missing_resource(
        self, mocked_aws: None, simple_cfg: Path
    ) -> None:
        """If a resource is in state but missing in AWS, deploy recreates it."""
        from infrakit.providers.dynamodb import DynamoDBProvider

        # Deploy to populate state
        runner.invoke(app, ["deploy", "--config", str(simple_cfg), "--auto-approve"])

        # Simulate drift: delete the table directly via AWS without updating state
        from infrakit.core.session import AWSSession
        client = AWSSession.client("dynamodb")
        client.delete_table(TableName="idem-test-dev-items_table")

        # Deploy again — should detect drift and recreate
        result = runner.invoke(
            app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
        )
        assert result.exit_code == 0
        assert "drift" in result.stdout.lower() or "recreating" in result.stdout.lower()

        # Table should now exist again
        cfg = load_config(str(simple_cfg))
        provider = DynamoDBProvider(
            "items_table",
            cfg.services["items_table"],
            project="idem-test",
            env="dev",
        )
        assert provider.exists() is True

    def test_no_changes_message_when_all_resources_exist(
        self, mocked_aws: None, simple_cfg: Path
    ) -> None:
        """The specific 'All resources up to date.' message appears on second deploy."""
        runner.invoke(app, ["deploy", "--config", str(simple_cfg), "--auto-approve"])
        result = runner.invoke(
            app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
        )
        assert "All resources up to date" in result.stdout

    def test_first_deploy_shows_creating(
        self, mocked_aws: None, simple_cfg: Path
    ) -> None:
        """The first deploy shows 'creating' for new resources."""
        result = runner.invoke(
            app, ["deploy", "--config", str(simple_cfg), "--auto-approve"]
        )
        assert result.exit_code == 0
        assert "creating" in result.stdout.lower()
        assert "Deploy complete" in result.stdout
