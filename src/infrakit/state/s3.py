"""S3 + DynamoDB remote state backend.

State is stored as a JSON object in S3. A DynamoDB table provides
distributed locking so concurrent deploys from different CI runners
(or developers) cannot corrupt state. This is the same pattern used
by Terraform's S3 backend.

Prerequisites (the user must create these before using this backend):
- An S3 bucket for state storage
- A DynamoDB table with primary key ``LockID`` (String)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from infrakit.core.session import AWSSession
from infrakit.state.backend import StateBackend, StateLockError
from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


class S3StateBackend(StateBackend):
    """Remote state backend using S3 (storage) + DynamoDB (locking).

    State file path in S3::

        {key_prefix}/{project}/{env}/state.json

    DynamoDB lock item::

        {LockID: "infrakit/{project}/{env}", RunID: "...", LockedAt: "..."}
    """

    def __init__(
        self,
        bucket: str,
        lock_table: str,
        key_prefix: str = "infrakit",
        project: str = "",
        env: str = "",
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._state_key = f"{key_prefix}/{project}/{env}/state.json"
        self._lock_id = f"infrakit/{project}/{env}"
        self._lock_table = lock_table
        self._s3 = AWSSession.client("s3", region_name=region)
        self._ddb = AWSSession.client("dynamodb", region_name=region)

    # ------------------------------------------------------------------
    # StateBackend interface
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._state_key)
            body = resp["Body"].read().decode("utf-8")
            state: dict[str, Any] = json.loads(body)
            logger.debug("State loaded from s3://%s/%s", self._bucket, self._state_key)
            return state
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "NoSuchKey":
                return {}
            raise

    def save(self, state: dict[str, Any]) -> None:
        body = json.dumps(state, indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._state_key,
            Body=body,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        logger.debug("State saved to s3://%s/%s", self._bucket, self._state_key)

    def lock(self, run_id: str) -> None:
        try:
            self._ddb.put_item(
                TableName=self._lock_table,
                Item={
                    "LockID": {"S": self._lock_id},
                    "RunID": {"S": run_id},
                    "LockedAt": {"S": datetime.now(tz=UTC).isoformat()},
                },
                ConditionExpression="attribute_not_exists(LockID)",
            )
            logger.debug("State locked (run=%s, key=%s)", run_id, self._lock_id)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                raise StateLockError(
                    f"State is already locked by another deployment "
                    f"(lock key: {self._lock_id}). "
                    "If this is stale, delete the item from the DynamoDB lock table."
                ) from exc
            raise

    def unlock(self, run_id: str) -> None:
        try:
            self._ddb.delete_item(
                TableName=self._lock_table,
                Key={"LockID": {"S": self._lock_id}},
            )
            logger.debug("State unlocked (run=%s)", run_id)
        except ClientError:
            pass  # best-effort unlock

    def set_resource(
        self,
        name: str,
        resource_type: str,
        outputs: dict[str, Any],
        status: str = "created",
    ) -> None:
        state = self.load()
        state.setdefault("resources", {})[name] = {
            "type": resource_type,
            "outputs": outputs,
            "status": status,
        }
        self.save(state)

    def remove_resource(self, name: str) -> None:
        state = self.load()
        state.get("resources", {}).pop(name, None)
        self.save(state)
