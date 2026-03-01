"""Abstract state backend."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StateBackend(ABC):
    """Common interface for all state backends."""

    @abstractmethod
    def load(self) -> dict[str, Any]:
        """Return the current state dict, or ``{}`` if no state exists yet."""

    @abstractmethod
    def save(self, state: dict[str, Any]) -> None:
        """Persist *state* atomically."""

    @abstractmethod
    def lock(self, run_id: str) -> None:
        """Acquire an exclusive deployment lock.

        Raises ``StateLockError`` if already locked by another run.
        """

    @abstractmethod
    def unlock(self, run_id: str) -> None:
        """Release the deployment lock."""


class StateLockError(Exception):
    """Raised when the state is already locked by another deployment."""
