"""Unit tests for CLI commands using Typer's test runner."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from infrakit.cli.main import app

runner = CliRunner()


@pytest.fixture()
def valid_cfg(tmp_path: Path) -> Path:
    f = tmp_path / "infrakit.yaml"
    f.write_text(
        textwrap.dedent(f"""\
            project: test-app
            region: us-east-1
            env: dev
            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json
            services:
              my_table:
                type: dynamodb
                hash_key: id
                hash_key_type: S
        """),
        encoding="utf-8",
    )
    return f


@pytest.fixture()
def invalid_cfg(tmp_path: Path) -> Path:
    f = tmp_path / "infrakit.yaml"
    f.write_text("project: ''\nregion: bad\nenv: dev\nservices: {}\n", encoding="utf-8")
    return f


class TestValidateCommand:
    def test_validate_valid_config_exits_0(self, valid_cfg: Path) -> None:
        result = runner.invoke(app, ["validate", "--config", str(valid_cfg)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_validate_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(app, ["validate", "--config", str(invalid_cfg)])
        assert result.exit_code == 1

    def test_validate_missing_file_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", "--config", str(tmp_path / "missing.yaml")])
        assert result.exit_code == 1

    def test_validate_dangling_ref_exits_1(self, tmp_path: Path) -> None:
        f = tmp_path / "infrakit.yaml"
        f.write_text(
            textwrap.dedent("""\
                project: app
                region: us-east-1
                env: dev
                services:
                  fn:
                    type: lambda
                    handler: h.handler
                    runtime: python3.12
                    role: !ref nonexistent.arn
            """),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["validate", "--config", str(f)])
        assert result.exit_code == 1


class TestPlanCommand:
    def test_plan_empty_state_shows_creates(self, valid_cfg: Path) -> None:
        result = runner.invoke(app, ["plan", "--config", str(valid_cfg)])
        assert result.exit_code == 0

    def test_plan_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(app, ["plan", "--config", str(invalid_cfg)])
        assert result.exit_code == 1


class TestDeployCommand:
    def test_deploy_auto_approve(self, mocked_aws: None, valid_cfg: Path) -> None:
        result = runner.invoke(
            app, ["deploy", "--config", str(valid_cfg), "--auto-approve"]
        )
        assert result.exit_code == 0

    def test_deploy_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(
            app, ["deploy", "--config", str(invalid_cfg), "--auto-approve"]
        )
        assert result.exit_code == 1

    def test_deploy_missing_file_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["deploy", "--config", str(tmp_path / "nope.yaml"), "--auto-approve"]
        )
        assert result.exit_code == 1


class TestDestroyCommand:
    def test_destroy_auto_approve(self, mocked_aws: None, valid_cfg: Path) -> None:
        # Deploy first, then destroy
        runner.invoke(app, ["deploy", "--config", str(valid_cfg), "--auto-approve"])
        result = runner.invoke(
            app, ["destroy", "--config", str(valid_cfg), "--auto-approve"]
        )
        assert result.exit_code == 0

    def test_destroy_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(
            app, ["destroy", "--config", str(invalid_cfg), "--auto-approve"]
        )
        assert result.exit_code == 1


class TestStatusCommand:
    def test_status_empty_state(self, mocked_aws: None, valid_cfg: Path) -> None:
        result = runner.invoke(app, ["status", "--config", str(valid_cfg)])
        assert result.exit_code == 0

    def test_status_after_deploy(self, mocked_aws: None, valid_cfg: Path) -> None:
        runner.invoke(app, ["deploy", "--config", str(valid_cfg), "--auto-approve"])
        result = runner.invoke(app, ["status", "--config", str(valid_cfg)])
        assert result.exit_code == 0


class TestPlanJsonFlag:
    def test_plan_json_valid_config(self, valid_cfg: Path) -> None:
        import json

        result = runner.invoke(app, ["plan", "--config", str(valid_cfg), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "creates" in data
        assert "deletes" in data
        assert "has_changes" in data

    def test_plan_json_shows_creates(self, valid_cfg: Path) -> None:
        import json

        result = runner.invoke(app, ["plan", "--config", str(valid_cfg), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data["creates"]) == 1
        assert data["creates"][0]["name"] == "my_table"
        assert data["has_changes"] is True

    def test_plan_json_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(app, ["plan", "--config", str(invalid_cfg), "--json"])
        assert result.exit_code == 1


class TestDriftCommand:
    def test_drift_no_state_exits_0(self, mocked_aws: None, valid_cfg: Path) -> None:
        result = runner.invoke(app, ["drift", "--config", str(valid_cfg)])
        assert result.exit_code == 0

    def test_drift_all_ok_exits_0(self, mocked_aws: None, valid_cfg: Path) -> None:
        runner.invoke(app, ["deploy", "--config", str(valid_cfg), "--auto-approve"])
        result = runner.invoke(app, ["drift", "--config", str(valid_cfg)])
        assert result.exit_code == 0
        # The "No drift detected" summary line is written via typer.echo → stdout
        assert "No drift detected" in result.stdout

    def test_drift_missing_resource_exits_1(self, mocked_aws: None, valid_cfg: Path) -> None:
        from infrakit.core.session import AWSSession

        runner.invoke(app, ["deploy", "--config", str(valid_cfg), "--auto-approve"])
        # Delete the table out-of-band
        AWSSession.client("dynamodb").delete_table(TableName="test-app-dev-my_table")
        result = runner.invoke(app, ["drift", "--config", str(valid_cfg)])
        assert result.exit_code == 1
        # The "Drift detected: N missing" summary line is written via typer.echo → stdout
        assert "missing" in result.stdout

    def test_drift_json_flag_outputs_valid_json(
        self, mocked_aws: None, valid_cfg: Path
    ) -> None:
        import json

        runner.invoke(app, ["deploy", "--config", str(valid_cfg), "--auto-approve"])
        result = runner.invoke(app, ["drift", "--config", str(valid_cfg), "--json"])
        data = json.loads(result.stdout)
        assert "resources" in data
        assert "has_drift" in data
        assert "summary" in data
        assert data["has_drift"] is False

    def test_drift_invalid_config_exits_1(self, invalid_cfg: Path) -> None:
        result = runner.invoke(app, ["drift", "--config", str(invalid_cfg)])
        assert result.exit_code == 1
