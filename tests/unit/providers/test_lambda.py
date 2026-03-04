"""Unit tests for the Lambda provider."""

from __future__ import annotations

from unittest.mock import call, patch

import pytest
from botocore.exceptions import ClientError

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

    def test_create_retries_on_iam_propagation_lag(self, provider: LambdaProvider) -> None:
        """create() retries when IAM role hasn't propagated yet."""
        call_count = 0
        original_create = provider._client.create_function

        def flaky_create(**kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "InvalidParameterValueException",
                            "Message": "The role defined for the function cannot be assumed by Lambda.",
                        }
                    },
                    "CreateFunction",
                )
            return original_create(**kwargs)

        with (
            patch.object(provider._client, "create_function", side_effect=flaky_create),
            patch("infrakit.providers.lambda_.time.sleep"),
        ):
            outputs = provider.create()

        assert call_count == 2
        assert "arn" in outputs

    def test_create_raises_after_max_retries(self, provider: LambdaProvider) -> None:
        """create() stops retrying after 6 attempts and raises RuntimeError."""

        def always_fail(**kwargs: object) -> object:
            raise ClientError(
                {
                    "Error": {
                        "Code": "InvalidParameterValueException",
                        "Message": "The role defined for the function cannot be assumed by Lambda.",
                    }
                },
                "CreateFunction",
            )

        with (
            patch.object(provider._client, "create_function", side_effect=always_fail),
            patch("infrakit.providers.lambda_.time.sleep"),
            pytest.raises(RuntimeError, match="never propagated"),
        ):
            provider.create()

    def test_create_with_function_url_outputs_url(self, mocked_aws: None, role_arn: str) -> None:
        cfg = LambdaResource(
            type="lambda",
            handler="h.handler",
            runtime="python3.12",
            role=role_arn,
            function_url=True,
        )
        p = LambdaProvider("url_fn", cfg, project="proj", env="dev")
        with patch.object(
            p,
            "_ensure_function_url",
            return_value="https://abc.lambda-url.us-east-1.on.aws/",
        ):
            outputs = p.create()
        assert outputs["function_url"] == "https://abc.lambda-url.us-east-1.on.aws/"

    def test_ensure_function_url_adds_required_permissions(
        self, mocked_aws: None, role_arn: str
    ) -> None:
        cfg = LambdaResource(type="lambda", handler="h.handler", runtime="python3.12", role=role_arn)
        p = LambdaProvider("url_permissions_fn", cfg, project="proj", env="dev")

        with (
            patch.object(
                p._client,
                "create_function_url_config",
                return_value={"FunctionUrl": "https://abc.lambda-url.us-east-1.on.aws/"},
            ),
            patch.object(p._client, "add_permission") as add_permission,
        ):
            function_url = p._ensure_function_url()

        assert function_url == "https://abc.lambda-url.us-east-1.on.aws/"
        assert add_permission.call_count == 2
        add_permission.assert_has_calls(
            [
                call(
                    FunctionName=p.physical_name,
                    StatementId="function-url-public",
                    Action="lambda:InvokeFunctionUrl",
                    Principal="*",
                    FunctionUrlAuthType="NONE",
                ),
                call(
                    FunctionName=p.physical_name,
                    StatementId="function-url-public-invoke",
                    Action="lambda:InvokeFunction",
                    Principal="*",
                    InvokedViaFunctionUrl=True,
                ),
            ],
            any_order=False,
        )

    def test_ensure_function_url_uses_existing_url_on_conflict(
        self, mocked_aws: None, role_arn: str
    ) -> None:
        cfg = LambdaResource(type="lambda", handler="h.handler", runtime="python3.12", role=role_arn)
        p = LambdaProvider("url_conflict_fn", cfg, project="proj", env="dev")
        conflict = ClientError(
            {"Error": {"Code": "ResourceConflictException", "Message": "exists"}},
            "CreateFunctionUrlConfig",
        )

        with (
            patch.object(p._client, "create_function_url_config", side_effect=conflict),
            patch.object(
                p._client,
                "get_function_url_config",
                return_value={"FunctionUrl": "https://existing.lambda-url.us-east-1.on.aws/"},
            ) as get_function_url_config,
            patch.object(p._client, "add_permission"),
        ):
            function_url = p._ensure_function_url()

        get_function_url_config.assert_called_once_with(FunctionName=p.physical_name)
        assert function_url == "https://existing.lambda-url.us-east-1.on.aws/"
