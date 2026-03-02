"""Unit tests for state/local.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrakit.state.backend import StateLockError
from infrakit.state.local import LocalStateBackend


class TestLocalStateBackend:
    @pytest.fixture()
    def backend(self, tmp_path: Path) -> LocalStateBackend:
        return LocalStateBackend(tmp_path / ".infrakit" / "state.json")

    def test_load_returns_empty_dict_when_no_file(self, backend: LocalStateBackend) -> None:
        assert backend.load() == {}

    def test_save_and_load_roundtrip(self, backend: LocalStateBackend) -> None:
        state = {"version": 1, "resources": {"my_table": {"type": "dynamodb"}}}
        backend.save(state)
        assert backend.load() == state

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        b = LocalStateBackend(tmp_path / "deep" / "nested" / "state.json")
        b.save({"resources": {}})
        assert (tmp_path / "deep" / "nested" / "state.json").exists()

    def test_save_is_atomic(self, backend: LocalStateBackend, tmp_path: Path) -> None:
        """No partial writes: tmp file renamed atomically."""
        backend.save({"resources": {"a": 1}})
        # No tmp files should remain
        tmp_files = list(tmp_path.rglob(".infrakit-state-*.tmp"))
        assert tmp_files == []

    def test_lock_and_unlock(self, backend: LocalStateBackend) -> None:
        backend.lock("run-001")
        backend.unlock("run-001")
        # Lock file removed after unlock
        assert not backend._lock_path.exists()

    def test_double_lock_raises(self, backend: LocalStateBackend) -> None:
        backend.lock("run-001")
        with pytest.raises(StateLockError, match="run-001"):
            backend.lock("run-002")
        backend.unlock("run-001")

    def test_unlock_when_not_locked_is_safe(self, backend: LocalStateBackend) -> None:
        backend.unlock("run-xyz")  # should not raise

    def test_set_resource_and_get_resource(self, backend: LocalStateBackend) -> None:
        backend.set_resource("my_table", "dynamodb", {"name": "tbl", "arn": "arn:aws:..."})
        entry = backend.get_resource("my_table")
        assert entry is not None
        assert entry["outputs"]["name"] == "tbl"
        assert entry["status"] == "created"

    def test_get_resource_returns_none_for_unknown(self, backend: LocalStateBackend) -> None:
        assert backend.get_resource("does_not_exist") is None

    def test_remove_resource(self, backend: LocalStateBackend) -> None:
        backend.set_resource("r", "s3", {"name": "bucket"})
        backend.remove_resource("r")
        assert backend.get_resource("r") is None

    def test_remove_resource_missing_is_safe(self, backend: LocalStateBackend) -> None:
        backend.remove_resource("nonexistent")  # should not raise
