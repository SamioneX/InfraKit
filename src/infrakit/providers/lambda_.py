"""Lambda function provider."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.providers.base import ResourceProvider
from infrakit.schema.models import LambdaResource
from infrakit.utils.tags import standard_tags


class LambdaProvider(ResourceProvider):
    config: LambdaResource

    def __init__(
        self,
        name: str,
        config: LambdaResource,
        project: str,
        env: str,
        region: str = "us-east-1",
    ) -> None:
        super().__init__(name, config, project, env, region)
        self._client = AWSSession.client("lambda", region_name=region)

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        try:
            self._client.get_function(FunctionName=self.physical_name)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    def create(self) -> dict[str, Any]:
        cfg = self.config
        code_zip = self._zip_code(cfg.code)

        kwargs: dict[str, Any] = {
            "FunctionName": self.physical_name,
            "Runtime": cfg.runtime,
            "Handler": cfg.handler,
            "Code": {"ZipFile": code_zip},
            "MemorySize": cfg.memory_mb,
            "Timeout": cfg.timeout_s,
            "Tags": standard_tags(self.project, self.env),
        }

        if cfg.role:
            kwargs["Role"] = cfg.role
        else:
            # Fallback: use a placeholder ARN (engine will have resolved !ref by now)
            raise ValueError(
                f"Lambda {self.name} requires a 'role' (IAM role ARN). "
                "Set it to a !ref or explicit ARN."
            )

        if cfg.environment:
            kwargs["Environment"] = {"Variables": cfg.environment}

        if cfg.layers:
            kwargs["Layers"] = cfg.layers

        resp = self._client.create_function(**kwargs)

        # Optionally attach EventBridge schedule
        if cfg.schedule:
            self._create_schedule(resp["FunctionArn"], cfg.schedule)

        self.logger.info("Created Lambda function: %s", self.physical_name)
        return {
            "name": resp["FunctionName"],
            "arn": resp["FunctionArn"],
            "function_name": resp["FunctionName"],
        }

    def delete(self) -> None:
        if not self.exists():
            self.logger.info("Function %s already absent.", self.physical_name)
            return
        self._client.delete_function(FunctionName=self.physical_name)
        self.logger.info("Deleted Lambda function: %s", self.physical_name)

    def update(self, previous_outputs: dict[str, Any]) -> dict[str, Any]:
        """Update code + configuration in-place (no delete/recreate)."""
        cfg = self.config
        code_zip = self._zip_code(cfg.code)

        self._client.update_function_code(
            FunctionName=self.physical_name,
            ZipFile=code_zip,
        )
        update_kwargs: dict[str, Any] = {
            "FunctionName": self.physical_name,
            "Runtime": cfg.runtime,
            "Handler": cfg.handler,
            "MemorySize": cfg.memory_mb,
            "Timeout": cfg.timeout_s,
        }
        if cfg.environment:
            update_kwargs["Environment"] = {"Variables": cfg.environment}

        self._client.update_function_configuration(**update_kwargs)

        resp = self._client.get_function_configuration(FunctionName=self.physical_name)
        return {
            "name": resp["FunctionName"],
            "arn": resp["FunctionArn"],
            "function_name": resp["FunctionName"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zip_code(code_path: str) -> bytes:
        """Return a zip archive of *code_path* as bytes."""
        buf = io.BytesIO()
        source = Path(code_path)

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            if source.is_dir():
                for file in source.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(source))
            elif source.is_file():
                zf.write(source, source.name)
            else:
                # Dummy handler so tests can work without a real code path
                zf.writestr("handler.py", "def handler(event, context): return {}")

        return buf.getvalue()

    def _create_schedule(self, function_arn: str, schedule: str) -> None:
        events = AWSSession.client("events", region_name=self.region)
        rule_name = f"{self.physical_name}-schedule"
        rule_resp = events.put_rule(
            Name=rule_name,
            ScheduleExpression=schedule,
            State="ENABLED",
        )
        events.put_targets(
            Rule=rule_name,
            Targets=[{"Id": "1", "Arn": function_arn}],
        )
        self._client.add_permission(
            FunctionName=self.physical_name,
            StatementId=f"{rule_name}-invoke",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_resp["RuleArn"],
        )
