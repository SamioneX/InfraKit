"""Unit tests for schema/models.py and schema/validator.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from infrakit.schema.models import (
    DynamoDBResource,
    InfraKitConfig,
    LambdaResource,
    LocalStateConfig,
)
from infrakit.schema.validator import ConfigError, load_config, validate_refs

# ---------------------------------------------------------------------------
# InfraKitConfig model tests
# ---------------------------------------------------------------------------


class TestInfraKitConfig:
    def test_minimal_valid_config(self) -> None:
        cfg = InfraKitConfig(project="myapp", region="us-east-1", env="dev", services={})
        assert cfg.project == "myapp"
        assert isinstance(cfg.state, LocalStateConfig)

    def test_project_name_validation(self) -> None:
        with pytest.raises(Exception, match="project"):
            InfraKitConfig(project="My App!", region="us-east-1", env="dev", services={})

    def test_empty_project_name_rejected(self) -> None:
        with pytest.raises(Exception):
            InfraKitConfig(project="", region="us-east-1", env="dev", services={})

    def test_invalid_region_rejected(self) -> None:
        with pytest.raises(Exception, match="region"):
            InfraKitConfig(project="app", region="not-a-region", env="dev", services={})

    def test_invalid_env_rejected(self) -> None:
        with pytest.raises(Exception):
            InfraKitConfig(project="app", region="us-east-1", env="production", services={})  # type: ignore[arg-type]


class TestDynamoDBResource:
    def test_valid_pay_per_request(self) -> None:
        r = DynamoDBResource(type="dynamodb", hash_key="id", hash_key_type="S")
        assert r.billing == "pay-per-request"

    def test_provisioned_without_capacity_rejected(self) -> None:
        with pytest.raises(Exception, match="read_capacity"):
            DynamoDBResource(type="dynamodb", hash_key="id", billing="provisioned")

    def test_provisioned_with_capacity_valid(self) -> None:
        r = DynamoDBResource(
            type="dynamodb",
            hash_key="id",
            billing="provisioned",
            read_capacity=5,
            write_capacity=5,
        )
        assert r.read_capacity == 5

    def test_sort_key_optional(self) -> None:
        r = DynamoDBResource(type="dynamodb", hash_key="pk", sort_key="sk", hash_key_type="S")
        assert r.sort_key == "sk"


class TestLambdaResource:
    def test_valid_runtime(self) -> None:
        r = LambdaResource(type="lambda", handler="app.handler", runtime="python3.12")
        assert r.runtime == "python3.12"

    def test_invalid_runtime_rejected(self) -> None:
        with pytest.raises(Exception, match="runtime"):
            LambdaResource(type="lambda", handler="app.handler", runtime="ruby3.0")

    def test_memory_bounds(self) -> None:
        with pytest.raises(Exception):
            LambdaResource(type="lambda", handler="h", memory_mb=64)

    def test_timeout_bounds(self) -> None:
        with pytest.raises(Exception):
            LambdaResource(type="lambda", handler="h", timeout_s=0)


# ---------------------------------------------------------------------------
# load_config tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_loads_valid_file(self, valid_config_path: Path) -> None:
        cfg = load_config(valid_config_path)
        assert cfg.project == "my-api"
        assert cfg.env == "dev"
        assert "users_table" in cfg.services

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("project: [\nunclosed bracket", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML parse error"):
            load_config(bad_yaml)

    def test_non_mapping_yaml_raises_config_error(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "list.yaml"
        bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="mapping"):
            load_config(bad_yaml)

    def test_validation_errors_produce_readable_message(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "infrakit.yaml"
        cfg_file.write_text(
            textwrap.dedent("""\
                project: ""
                region: not-a-region
                env: dev
                services: {}
            """),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="validation failed"):
            load_config(cfg_file)

    def test_ref_tags_preserved_as_strings(self, valid_config_path: Path) -> None:
        cfg = load_config(valid_config_path)
        # The !ref value on api_handler.role should start with "!ref"
        from infrakit.schema.models import LambdaResource

        handler = cfg.services["api_handler"]
        assert isinstance(handler, LambdaResource)
        assert handler.role is not None and handler.role.startswith("!ref")


# ---------------------------------------------------------------------------
# validate_refs tests
# ---------------------------------------------------------------------------


class TestValidateRefs:
    def test_valid_refs_return_no_errors(self, valid_config_path: Path) -> None:
        cfg = load_config(valid_config_path)
        errors = validate_refs(cfg)
        assert errors == []

    def test_dangling_ref_returns_error(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "infrakit.yaml"
        cfg_file.write_text(
            textwrap.dedent("""\
                project: test-app
                region: us-east-1
                env: dev
                services:
                  my_lambda:
                    type: lambda
                    handler: app.handler
                    runtime: python3.12
                    role: !ref nonexistent_role.arn
            """),
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        errors = validate_refs(cfg)
        assert any("nonexistent_role" in e for e in errors)
