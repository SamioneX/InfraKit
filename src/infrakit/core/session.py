"""AWS session Singleton.

A single boto3 Session is created per process and shared across all providers.
This minimises connection overhead and provides a single injection point for
mocking in tests::

    from infrakit.core.session import AWSSession
    AWSSession.configure(region="us-west-2", profile="my-profile")
    s3 = AWSSession.client("s3")
"""

from __future__ import annotations

import threading
from typing import Any

import boto3
from botocore.client import BaseClient

from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


class AWSSession:
    """Process-wide AWS session Singleton."""

    _session: boto3.Session | None = None
    _lock: threading.Lock = threading.Lock()
    _region: str = "us-east-1"
    _profile: str | None = None

    # ------------------------------------------------------------------
    # Configuration (call before first client() call)
    # ------------------------------------------------------------------

    @classmethod
    def configure(
        cls,
        region: str = "us-east-1",
        profile: str | None = None,
    ) -> None:
        """Set the region/profile for subsequent calls.

        Calling this after the session has been initialised resets the
        Singleton so the new settings take effect.
        """
        with cls._lock:
            cls._region = region
            cls._profile = profile
            cls._session = None  # force re-creation

    # ------------------------------------------------------------------
    # Internal session access
    # ------------------------------------------------------------------

    @classmethod
    def _get_session(cls) -> boto3.Session:
        if cls._session is None:
            with cls._lock:
                if cls._session is None:
                    cls._session = boto3.Session(
                        region_name=cls._region,
                        profile_name=cls._profile,
                    )
                    logger.debug(
                        "AWS session created: region=%s profile=%s",
                        cls._region,
                        cls._profile or "default",
                    )
        return cls._session

    # ------------------------------------------------------------------
    # Public client / resource factories
    # ------------------------------------------------------------------

    @classmethod
    def client(cls, service: str, **kwargs: Any) -> BaseClient:
        """Return a boto3 client for *service* using the shared session."""
        return cls._get_session().client(service, **kwargs)  # type: ignore[return-value]

    @classmethod
    def resource(cls, service: str, **kwargs: Any) -> Any:
        """Return a boto3 resource for *service* using the shared session."""
        return cls._get_session().resource(service, **kwargs)

    @classmethod
    def reset(cls) -> None:
        """Destroy the cached session (used in tests)."""
        with cls._lock:
            cls._session = None
