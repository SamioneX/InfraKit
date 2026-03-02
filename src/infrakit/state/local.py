"""Local file state backend (Phase 1 default).

State is stored as a JSON file on disk. Locking uses a companion
``.lock`` file — sufficient for single-developer use, but not safe
for concurrent CI runners (use the S3 backend for that).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from infrakit.state.backend import StateBackend, StateLockError
from infrakit.utils.logging import get_logger

logger = get_logger(__name__)


class LocalStateBackend(StateBackend):
    """Stores state in a JSON file at *path*.

    The state file format::

        {
          "version": 1,
          "project": "my-api",
          "env": "prod",
          "resources": {
            "users_table": {
              "type": "dynamodb",
              "outputs": {"name": "...", "arn": "..."},
              "status": "created"
            }
          }
        }
    """

    def __init__(self, path: str | Path = ".infrakit/state.json") -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(".lock")

    # ------------------------------------------------------------------
    # StateBackend interface
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        text = self._path.read_text(encoding="utf-8")
        state: dict[str, Any] = json.loads(text)
        return state

    def save(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, prefix=".infrakit-state-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        logger.debug("State saved to %s", self._path)

    def lock(self, run_id: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._lock_path.exists():
            existing = self._lock_path.read_text(encoding="utf-8").strip()
            raise StateLockError(
                f"State is locked by run '{existing}'. "
                "If this is stale, delete: " + str(self._lock_path)
            )
        self._lock_path.write_text(run_id, encoding="utf-8")
        logger.debug("State locked by run %s", run_id)

    def unlock(self, run_id: str) -> None:
        if self._lock_path.exists():
            self._lock_path.unlink()
            logger.debug("State unlocked by run %s", run_id)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_resource(self, name: str) -> dict[str, Any] | None:
        """Return the stored resource entry for *name*, or None."""
        state = self.load()
        return state.get("resources", {}).get(name)

    def set_resource(
        self,
        name: str,
        resource_type: str,
        outputs: dict[str, Any],
        status: str = "created",
    ) -> None:
        """Upsert a single resource entry and save state."""
        state = self.load()
        state.setdefault("resources", {})[name] = {
            "type": resource_type,
            "outputs": outputs,
            "status": status,
        }
        self.save(state)

    def remove_resource(self, name: str) -> None:
        """Remove a resource entry from state and save."""
        state = self.load()
        state.get("resources", {}).pop(name, None)
        self.save(state)
