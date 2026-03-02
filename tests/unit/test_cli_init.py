"""Unit tests for the ``infrakit init`` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from infrakit.cli.main import app
from infrakit.schema.validator import load_config

runner = CliRunner()


class TestInitCommand:
    def test_init_serverless_api_creates_yaml(self, tmp_path: Path) -> None:
        """Choosing template 1 (serverless-api) writes a valid infrakit.yaml."""
        result = runner.invoke(
            app,
            ["init", "--output", str(tmp_path / "infrakit.yaml")],
            input="my-project\n1\nus-east-1\n",
        )
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "infrakit.yaml").exists()
        content = (tmp_path / "infrakit.yaml").read_text()
        assert "serverless-api" in content
        assert "project: my-project" in content
        assert "region:  us-east-1" in content

    def test_init_data_store_creates_yaml(self, tmp_path: Path) -> None:
        """Choosing template 2 (data-store) writes a valid infrakit.yaml."""
        result = runner.invoke(
            app,
            ["init", "--output", str(tmp_path / "infrakit.yaml")],
            input="data-app\n2\nca-central-1\n",
        )
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "infrakit.yaml").exists()
        content = (tmp_path / "infrakit.yaml").read_text()
        assert "data-store" in content
        assert "project: data-app" in content
        assert "dynamodb" in content

    def test_init_aborts_when_file_exists_and_user_declines(self, tmp_path: Path) -> None:
        """Declining overwrite when output already exists exits cleanly."""
        output = tmp_path / "infrakit.yaml"
        output.write_text("original", encoding="utf-8")
        result = runner.invoke(
            app,
            ["init", "--output", str(output)],
            input="my-project\n1\nus-east-1\nn\n",  # 'n' = do not overwrite
        )
        assert result.exit_code == 0
        # File must not have been overwritten
        assert output.read_text() == "original"

    def test_init_overwrites_when_user_confirms(self, tmp_path: Path) -> None:
        """Confirming overwrite replaces the existing file."""
        output = tmp_path / "infrakit.yaml"
        output.write_text("original", encoding="utf-8")
        result = runner.invoke(
            app,
            ["init", "--output", str(output)],
            input="new-project\n1\nus-east-1\ny\n",  # 'y' = overwrite
        )
        assert result.exit_code == 0, result.stdout
        assert "new-project" in output.read_text()

    def test_init_invalid_template_choice_exits_1(self, tmp_path: Path) -> None:
        """Entering an invalid template number exits with code 1."""
        result = runner.invoke(
            app,
            ["init", "--output", str(tmp_path / "infrakit.yaml")],
            input="my-project\n99\n",
        )
        assert result.exit_code == 1

    def test_init_generated_serverless_api_yaml_is_valid(self, tmp_path: Path) -> None:
        """The generated serverless-api YAML passes schema validation."""
        output = tmp_path / "infrakit.yaml"
        runner.invoke(
            app,
            ["init", "--output", str(output)],
            input="portal\n1\nus-east-1\n",
        )
        cfg = load_config(str(output))
        assert cfg.project == "portal"
        assert cfg.region == "us-east-1"
        # Must have IAM role, lambda, and api-gateway resources
        types = {r.type for r in cfg.services.values()}  # type: ignore[union-attr]
        assert "iam-role" in types
        assert "lambda" in types
        assert "api-gateway" in types

    def test_init_generated_data_store_yaml_is_valid(self, tmp_path: Path) -> None:
        """The generated data-store YAML passes schema validation."""
        output = tmp_path / "infrakit.yaml"
        runner.invoke(
            app,
            ["init", "--output", str(output)],
            input="store\n2\neu-west-1\n",
        )
        cfg = load_config(str(output))
        assert cfg.project == "store"
        types = {r.type for r in cfg.services.values()}  # type: ignore[union-attr]
        assert "iam-role" in types
        assert "dynamodb" in types
        assert "lambda" in types

    def test_init_output_shows_next_steps(self, tmp_path: Path) -> None:
        """The success output includes helpful next steps."""
        result = runner.invoke(
            app,
            ["init", "--output", str(tmp_path / "infrakit.yaml")],
            input="hello\n1\nus-east-1\n",
        )
        assert result.exit_code == 0
        assert "Next steps" in result.stdout
        assert "validate" in result.stdout

    def test_init_uses_cwd_name_as_default_project(self, tmp_path: Path) -> None:
        """Pressing Enter on the project name prompt uses the CWD name."""
        output = tmp_path / "infrakit.yaml"
        # Pass empty string for project name — should default to cwd name
        result = runner.invoke(
            app,
            ["init", "--output", str(output)],
            input="\n1\nus-east-1\n",  # empty → default
        )
        # Should not crash and should create a file
        assert result.exit_code == 0
        assert output.exists()
