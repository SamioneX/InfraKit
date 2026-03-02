"""DynamoDB table provider."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import DynamoDBResource
from infrakit.utils.tags import standard_tags, to_boto3_tags


class DynamoDBProvider(ResourceProvider):
    config: DynamoDBResource

    def __init__(
        self,
        name: str,
        config: DynamoDBResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("dynamodb", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            self._client.describe_table(TableName=self.physical_name)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        key_schema = [{"AttributeName": cfg.hash_key, "KeyType": "HASH"}]
        attr_defs = [{"AttributeName": cfg.hash_key, "AttributeType": cfg.hash_key_type}]

        if cfg.sort_key:
            key_schema.append({"AttributeName": cfg.sort_key, "KeyType": "RANGE"})
            attr_defs.append(
                {"AttributeName": cfg.sort_key, "AttributeType": cfg.sort_key_type or "S"}
            )

        kwargs: dict[str, Any] = {
            "TableName": self.physical_name,
            "KeySchema": key_schema,
            "AttributeDefinitions": attr_defs,
            "Tags": to_boto3_tags(standard_tags(self.project, self.env)),
        }

        if cfg.billing == "pay-per-request":
            kwargs["BillingMode"] = "PAY_PER_REQUEST"
        else:
            kwargs["BillingMode"] = "PROVISIONED"
            kwargs["ProvisionedThroughput"] = {
                "ReadCapacityUnits": cfg.read_capacity or 5,
                "WriteCapacityUnits": cfg.write_capacity or 5,
            }

        if cfg.stream:
            kwargs["StreamSpecification"] = {
                "StreamEnabled": True,
                "StreamViewType": "NEW_AND_OLD_IMAGES",
            }

        resp = self._client.create_table(**kwargs)
        table = resp["TableDescription"]

        # Wait for table to be ACTIVE before any further calls
        self._client.get_waiter("table_exists").wait(TableName=self.physical_name)
        # Re-fetch to get final ARN / stream ARN
        table = self._client.describe_table(TableName=self.physical_name)["Table"]

        # Optionally enable TTL
        if cfg.ttl_attribute:
            self._client.update_time_to_live(
                TableName=self.physical_name,
                TimeToLiveSpecification={
                    "Enabled": True,
                    "AttributeName": cfg.ttl_attribute,
                },
            )

        self.logger.info("Created DynamoDB table: %s", self.physical_name)
        return self._build_outputs(table)

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("Table %s already absent, nothing to do.", self.physical_name)
            return
        self._client.delete_table(TableName=self.physical_name)
        self._client.get_waiter("table_not_exists").wait(TableName=self.physical_name)
        self.logger.info("Deleted DynamoDB table: %s", self.physical_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_outputs(self, table: dict[str, Any]) -> dict[str, Any]:
        outputs: dict[str, Any] = {
            "name": table["TableName"],
            "arn": table["TableArn"],
        }
        if "LatestStreamArn" in table:
            outputs["stream_arn"] = table["LatestStreamArn"]
        return outputs
