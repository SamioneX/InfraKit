"""Unit tests for the Lambda provider."""

from __future__ import annotations

import pytest

from infrakit.providers.iam import IAMProvider
from infrakit.providers.lambda_ import LambdaProvider
from infrakit.schema.models import IAMRoleResource, LambdaResource


@pytest.fixture()
def role_arn(mocked_aws: None) -> str:
    """Create a real IAM role in moto and return its ARN."""
    cfg = IAMRoleResource(type="iam-role", assumed_by="lambda.amazonaws.com", policies=[])
    p = IAMProvider("exec_role", cfg, project="proj", env="dev")
    outputs = p.create()
    return str(outputs["arn"])


@pytest.fixture()
def provider(mocked_aws: None, role_arn: str) -> LambdaProvider:
    cfg = LambdaResource(
        type="lambda",
        handler="handler.handler",
        runtime="python3.12",
        role=role_arn,
    )
    return LambdaProvider("my_fn", cfg, project="proj", env="dev")


class TestLambdaProvider:
    def test_physical_name(self, provider: LambdaProvider) -> None:
        assert provider.physical_name == "proj-dev-my_fn"

    def test_exists_false_initially(self, provider: LambdaProvider) -> None:
        assert provider.exists() is False

    def test_create_returns_outputs(self, provider: LambdaProvider) -> None:
        outputs = provider.create()
        assert "name" in outputs
        assert "arn" in outputs
        assert "function_name" in outputs
        assert outputs["name"] == "proj-dev-my_fn"

    def test_exists_true_after_create(self, provider: LambdaProvider) -> None:
        provider.create()
        assert provider.exists() is True

    def test_delete_removes_function(self, provider: LambdaProvider) -> None:
        provider.create()
        provider.delete()
        assert provider.exists() is False

    def test_delete_when_not_exists_is_safe(self, provider: LambdaProvider) -> None:
        provider.delete()  # should not raise

    def test_create_without_role_raises(self, mocked_aws: None) -> None:
        cfg = LambdaResource(type="lambda", handler="h.handler", runtime="python3.12", role=None)
        p = LambdaProvider("fn", cfg, project="proj", env="dev")
        with pytest.raises(ValueError, match="role"):
            p.create()

    def test_update_replaces_code(self, provider: LambdaProvider) -> None:
        provider.create()
        outputs = provider.update({})
        assert "arn" in outputs

    def test_zip_code_dir(self, tmp_path: object) -> None:
        import pathlib

        d = pathlib.Path(str(tmp_path)) / "code"
        d.mkdir()
        (d / "app.py").write_text("def handler(e, c): return {}", encoding="utf-8")
        result = LambdaProvider._zip_code(str(d))
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_zip_code_file(self, tmp_path: object) -> None:
        import pathlib

        f = pathlib.Path(str(tmp_path)) / "app.py"
        f.write_text("def handler(e, c): return {}", encoding="utf-8")
        result = LambdaProvider._zip_code(str(f))
        assert isinstance(result, bytes)

    def test_zip_code_nonexistent_path_returns_dummy(self) -> None:
        result = LambdaProvider._zip_code("/nonexistent/path")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_environment_variables(self, mocked_aws: None, role_arn: str) -> None:
        cfg = LambdaResource(
            type="lambda",
            handler="h.handler",
            runtime="python3.12",
            role=role_arn,
            environment={"FOO": "bar", "TABLE": "my-table"},
        )
        p = LambdaProvider("env_fn", cfg, project="proj", env="dev")
        outputs = p.create()
        assert "arn" in outputs
