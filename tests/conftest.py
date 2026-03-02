"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from moto import mock_aws

from infrakit.core.session import AWSSession

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_aws_session() -> None:  # type: ignore[misc]
    """Reset the AWSSession Singleton before each test."""
    AWSSession.reset()
    yield
    AWSSession.reset()


@pytest.fixture()
def aws_credentials() -> None:
    """Set fake AWS credentials so moto doesn't complain."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture()
def mocked_aws(aws_credentials: None):  # type: ignore[misc]
    """Start moto AWS mocking for the duration of the test."""
    with mock_aws():
        AWSSession.configure(region="us-east-1")
        yield


@pytest.fixture()
def valid_config_path() -> Path:
    return FIXTURES_DIR / "valid_config.yaml"


@pytest.fixture()
def invalid_config_path() -> Path:
    return FIXTURES_DIR / "invalid_config.yaml"
