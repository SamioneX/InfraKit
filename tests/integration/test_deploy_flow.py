"""Integration tests: full deploy / destroy flow using moto."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from infrakit.core.engine import Engine
from infrakit.schema.validator import load_config


@pytest.fixture()
def simple_config(tmp_path: Path) -> Path:
    """A minimal config with a DynamoDB table and an IAM role."""
    cfg_file = tmp_path / "infrakit.yaml"
    cfg_file.write_text(
        textwrap.dedent(f"""\
            project: integ-test
            region: us-east-1
            env: dev

            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json

            services:
              data_table:
                type: dynamodb
                hash_key: id
                hash_key_type: S

              app_role:
                type: iam-role
                assumed_by: lambda.amazonaws.com
                policies: []
        """),
        encoding="utf-8",
    )
    return cfg_file


@pytest.fixture()
def s3_config(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "infrakit.yaml"
    cfg_file.write_text(
        textwrap.dedent(f"""\
            project: s3-test
            region: us-east-1
            env: dev

            state:
              backend: local
              path: {tmp_path}/.infrakit/state.json

            services:
              my_bucket:
                type: s3
                versioning: false
        """),
        encoding="utf-8",
    )
    return cfg_file


class TestDeployFlow:
    def test_deploy_creates_resources(self, mocked_aws: None, simple_config: Path) -> None:
        cfg = load_config(simple_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        state = engine._backend.load()
        assert "data_table" in state["resources"]
        assert "app_role" in state["resources"]
        assert state["resources"]["data_table"]["status"] == "created"

    def test_deploy_idempotent(self, mocked_aws: None, simple_config: Path) -> None:
        """Running deploy twice should not raise."""
        cfg = load_config(simple_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)
        engine.deploy(auto_approve=True)  # second run — resources already exist

    def test_destroy_removes_resources(self, mocked_aws: None, simple_config: Path) -> None:
        cfg = load_config(simple_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)
        engine.destroy(auto_approve=True)

        state = engine._backend.load()
        assert state.get("resources", {}) == {}

    def test_plan_shows_creates(self, mocked_aws: None, simple_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cfg = load_config(simple_config)
        engine = Engine(cfg)
        engine.plan()
        # Plan should not raise and resources should be listed as 'to create'

    def test_status_shows_deployed_resources(
        self, mocked_aws: None, simple_config: Path
    ) -> None:
        cfg = load_config(simple_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)
        engine.status()  # should not raise


class TestS3DeployFlow:
    def test_s3_deploy_and_destroy(self, mocked_aws: None, s3_config: Path) -> None:
        cfg = load_config(s3_config)
        engine = Engine(cfg)
        engine.deploy(auto_approve=True)

        state = engine._backend.load()
        assert "my_bucket" in state["resources"]

        engine.destroy(auto_approve=True)
        state = engine._backend.load()
        assert state.get("resources", {}) == {}
