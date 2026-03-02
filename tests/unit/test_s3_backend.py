"""Unit tests for the S3 + DynamoDB state backend."""

from __future__ import annotations

import boto3
import pytest

from infrakit.state.backend import StateLockError
from infrakit.state.s3 import S3StateBackend

BUCKET = "infrakit-test-state"
TABLE = "infrakit-test-locks"
REGION = "us-east-1"


@pytest.fixture()
def s3_backend(mocked_aws: None) -> S3StateBackend:
    """Create the S3 bucket and DynamoDB table, then return a backend instance."""
    # Create S3 bucket
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)

    # Create DynamoDB lock table
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    return S3StateBackend(
        bucket=BUCKET,
        lock_table=TABLE,
        key_prefix="infrakit",
        project="myapp",
        env="dev",
        region=REGION,
    )


class TestS3StateBackend:
    def test_load_returns_empty_on_new_bucket(self, s3_backend: S3StateBackend) -> None:
        state = s3_backend.load()
        assert state == {}

    def test_save_then_load(self, s3_backend: S3StateBackend) -> None:
        data = {"version": 1, "resources": {"foo": {"type": "s3", "outputs": {}, "status": "created"}}}
        s3_backend.save(data)
        loaded = s3_backend.load()
        assert loaded == data

    def test_lock_succeeds_first_time(self, s3_backend: S3StateBackend) -> None:
        s3_backend.lock("run-001")
        # Verify item is in DynamoDB
        ddb = boto3.client("dynamodb", region_name=REGION)
        resp = ddb.get_item(
            TableName=TABLE,
            Key={"LockID": {"S": "infrakit/myapp/dev"}},
        )
        assert "Item" in resp
        assert resp["Item"]["RunID"]["S"] == "run-001"

    def test_lock_raises_if_already_locked(self, s3_backend: S3StateBackend) -> None:
        s3_backend.lock("run-001")
        with pytest.raises(StateLockError, match="already locked"):
            s3_backend.lock("run-002")

    def test_unlock_releases_lock(self, s3_backend: S3StateBackend) -> None:
        s3_backend.lock("run-001")
        s3_backend.unlock("run-001")
        # Second lock should now succeed
        s3_backend.lock("run-002")  # no exception

    def test_set_resource(self, s3_backend: S3StateBackend) -> None:
        s3_backend.set_resource("my_table", "dynamodb", {"name": "foo", "arn": "arn:aws:..."})
        state = s3_backend.load()
        assert "my_table" in state["resources"]
        assert state["resources"]["my_table"]["type"] == "dynamodb"
        assert state["resources"]["my_table"]["outputs"]["name"] == "foo"

    def test_remove_resource(self, s3_backend: S3StateBackend) -> None:
        s3_backend.set_resource("my_table", "dynamodb", {"name": "foo"})
        s3_backend.remove_resource("my_table")
        state = s3_backend.load()
        assert "my_table" not in state.get("resources", {})

    def test_remove_nonexistent_resource_is_safe(self, s3_backend: S3StateBackend) -> None:
        s3_backend.remove_resource("does_not_exist")  # should not raise

    def test_set_resource_updates_existing(self, s3_backend: S3StateBackend) -> None:
        s3_backend.set_resource("res", "s3", {"name": "old"})
        s3_backend.set_resource("res", "s3", {"name": "new"})
        state = s3_backend.load()
        assert state["resources"]["res"]["outputs"]["name"] == "new"

    def test_state_key_format(self, s3_backend: S3StateBackend) -> None:
        assert s3_backend._state_key == "infrakit/myapp/dev/state.json"

    def test_lock_id_format(self, s3_backend: S3StateBackend) -> None:
        assert s3_backend._lock_id == "infrakit/myapp/dev"
