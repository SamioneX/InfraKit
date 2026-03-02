"""Unit tests for the API Gateway provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from infrakit.providers.api_gateway import APIGatewayProvider
from infrakit.providers.iam import IAMProvider
from infrakit.providers.lambda_ import LambdaProvider
from infrakit.schema.models import APIGatewayResource, IAMRoleResource, LambdaResource


@pytest.fixture()
def lambda_arn(mocked_aws: None) -> str:
    """Create a Lambda function and return its ARN."""
    role_cfg = IAMRoleResource(type="iam-role", assumed_by="lambda.amazonaws.com", policies=[])
    role = IAMProvider("exec_role", role_cfg, project="proj", env="dev")
    role_outputs = role.create()

    fn_cfg = LambdaResource(
        type="lambda",
        handler="h.handler",
        runtime="python3.12",
        role=role_outputs["arn"],
    )
    fn = LambdaProvider("api_fn", fn_cfg, project="proj", env="dev")
    outputs = fn.create()
    return str(outputs["arn"])


@pytest.fixture()
def provider(mocked_aws: None, lambda_arn: str) -> APIGatewayProvider:
    cfg = APIGatewayResource(
        type="api-gateway",
        integration=lambda_arn,
        routes=["GET /users", "POST /users"],
        stage="prod",
    )
    return APIGatewayProvider("my_api", cfg, project="proj", env="dev")


class TestAPIGatewayProvider:
    def test_physical_name(self, provider: APIGatewayProvider) -> None:
        assert provider.physical_name == "proj-dev-my_api"

    def test_exists_false_initially(self, provider: APIGatewayProvider) -> None:
        assert provider.exists() is False

    def test_create_returns_outputs(self, provider: APIGatewayProvider) -> None:
        outputs = provider.create()
        assert "id" in outputs
        assert "endpoint" in outputs

    def test_exists_true_after_create(self, provider: APIGatewayProvider) -> None:
        provider.create()
        assert provider.exists() is True

    def test_delete_removes_api(self, provider: APIGatewayProvider) -> None:
        provider.create()
        provider.delete()
        assert provider.exists() is False

    def test_delete_when_not_exists_is_safe(self, provider: APIGatewayProvider) -> None:
        provider.delete()  # should not raise

    def test_cors_enabled(self, mocked_aws: None, lambda_arn: str) -> None:
        cfg = APIGatewayResource(
            type="api-gateway",
            integration=lambda_arn,
            routes=["GET /health"],
            cors=True,
        )
        p = APIGatewayProvider("cors_api", cfg, project="proj", env="dev")
        outputs = p.create()
        assert "endpoint" in outputs

    def test_add_lambda_permission_idempotent_on_conflict(
        self, provider: APIGatewayProvider, lambda_arn: str
    ) -> None:
        """_add_lambda_permission silently ignores ResourceConflictException."""
        error = ClientError(
            {"Error": {"Code": "ResourceConflictException", "Message": "Statement already exists."}},
            "AddPermission",
        )
        mock_lambda_client = MagicMock()
        mock_lambda_client.add_permission.side_effect = error

        with patch("infrakit.providers.api_gateway.AWSSession.client", return_value=mock_lambda_client):
            provider._add_lambda_permission("api123", lambda_arn)  # must not raise
