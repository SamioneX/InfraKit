"""Unit tests for the S3 provider."""

from __future__ import annotations

import pytest

from infrakit.providers.s3 import S3Provider
from infrakit.schema.models import S3Resource


@pytest.fixture()
def provider(mocked_aws: None) -> S3Provider:
    cfg = S3Resource(type="s3")
    return S3Provider("uploads_bucket", cfg, project="myapp", env="dev")


class TestS3Provider:
    def test_physical_name(self, provider: S3Provider) -> None:
        assert provider.physical_name == "myapp-dev-uploads_bucket"

    def test_exists_false_initially(self, provider: S3Provider) -> None:
        assert provider.exists() is False

    def test_create_returns_outputs(self, provider: S3Provider) -> None:
        outputs = provider.create()
        assert "name" in outputs
        assert "arn" in outputs
        assert "bucket_url" in outputs
        assert outputs["name"] == "myapp-dev-uploads-bucket"

    def test_exists_true_after_create(self, provider: S3Provider) -> None:
        provider.create()
        assert provider.exists() is True

    def test_delete_removes_bucket(self, provider: S3Provider) -> None:
        provider.create()
        provider.delete()
        assert provider.exists() is False

    def test_delete_when_not_exists_is_safe(self, provider: S3Provider) -> None:
        provider.delete()  # should not raise

    def test_versioning_enabled(self, mocked_aws: None) -> None:
        cfg = S3Resource(type="s3", versioning=True)
        p = S3Provider("versioned", cfg, project="proj", env="dev")
        p.create()
        assert p.exists() is True
