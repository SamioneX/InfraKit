"""API Gateway v2 (HTTP API) provider."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import APIGatewayResource
from infrakit.utils.tags import standard_tags


class APIGatewayProvider(ResourceProvider):
    config: APIGatewayResource

    def __init__(
        self,
        name: str,
        config: APIGatewayResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("apigatewayv2", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            existing_id = self._find_api_id()
            return existing_id is not None
        except ClientError:
            return False

    def create(self) -> dict[str, Any]:
        cfg = self.config

        # Create the HTTP API
        api_kwargs: dict[str, Any] = {
            "Name": self.physical_name,
            "ProtocolType": "HTTP",
            "Tags": standard_tags(self.project, self.env),
        }
        if cfg.cors:
            api_kwargs["CorsConfiguration"] = {
                "AllowHeaders": ["*"],
                "AllowMethods": ["*"],
                "AllowOrigins": ["*"],
            }

        api_resp = self._client.create_api(**api_kwargs)
        api_id = api_resp["ApiId"]
        endpoint = api_resp["ApiEndpoint"]

        # Lambda integration — cfg.integration holds the resolved Lambda ARN
        integ_resp = self._client.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationUri=cfg.integration,
            PayloadFormatVersion="2.0",
        )
        integ_id = integ_resp["IntegrationId"]

        # Routes
        for route_spec in cfg.routes:
            parts = route_spec.split(None, 1)
            method = parts[0].upper()
            path = parts[1] if len(parts) > 1 else "/"
            self._client.create_route(
                ApiId=api_id,
                RouteKey=f"{method} {path}",
                Target=f"integrations/{integ_id}",
            )

        # Stage
        self._client.create_stage(
            ApiId=api_id,
            StageName=cfg.stage,
            AutoDeploy=True,
        )

        # Grant API Gateway permission to invoke the Lambda function
        self._add_lambda_permission(api_id, cfg.integration)

        self.logger.info("Created API Gateway: %s (%s)", self.physical_name, endpoint)
        return {
            "id": api_id,
            "endpoint": f"{endpoint}/{cfg.stage}",
        }

    def delete(self) -> None:
        api_id = self._find_api_id()
        if api_id is None:
            self.logger.info("API %s already absent.", self.physical_name)
            return
        self._client.delete_api(ApiId=api_id)
        self.logger.info("Deleted API Gateway: %s", self.physical_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_api_id(self) -> str | None:
        """Return the ApiId of an existing API with our physical name, or None."""
        paginator = self._client.get_paginator("get_apis")
        for page in paginator.paginate():
            for api in page["Items"]:
                if api["Name"] == self.physical_name:
                    return str(api["ApiId"])
        return None

    def _add_lambda_permission(self, api_id: str, function_arn: str) -> None:
        """Grant API Gateway permission to invoke the Lambda function."""
        lambda_client = AWSSession.client("lambda", region_name=self.region)
        # Extract account ID from Lambda ARN: arn:aws:lambda:region:account:function:name
        account_id = function_arn.split(":")[4]
        source_arn = f"arn:aws:execute-api:{self.region}:{account_id}:{api_id}/*/*"
        try:
            lambda_client.add_permission(
                FunctionName=function_arn,
                StatementId=f"apigateway-{api_id}",
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=source_arn,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceConflictException":
                pass  # permission already exists — idempotent
            else:
                raise
