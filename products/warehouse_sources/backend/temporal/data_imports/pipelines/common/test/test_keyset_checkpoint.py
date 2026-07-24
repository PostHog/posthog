from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import AsyncMock

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    persist_keyset_resume_state,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.keyset import KeysetResumeState


class _RecordingManager:
    def __init__(self):
        self.saved: list[Any] = []

    def save_state(self, data: KeysetResumeState) -> None:
        self.saved.append(data.last_key)


def _table(ids: list[int]) -> pa.Table:
    return pa.table({"id": ids, "body": [f"r{i}" for i in ids]})


@pytest.mark.asyncio
async def test_persists_max_key_of_committed_chunk():
    manager = _RecordingManager()
    await persist_keyset_resume_state(manager, "id", _table([3, 1, 2]), AsyncMock())  # type: ignore[arg-type]
    # Max, not last-appended, so an out-of-order chunk can't move the checkpoint backwards.
    assert manager.saved == [3]


@pytest.mark.asyncio
async def test_noop_without_keyset_column():
    manager = _RecordingManager()
    await persist_keyset_resume_state(manager, None, _table([1, 2]), AsyncMock())  # type: ignore[arg-type]
    assert manager.saved == []


@pytest.mark.asyncio
async def test_noop_without_manager():
    # No exception when the run isn't keyset-resumable.
    await persist_keyset_resume_state(None, "id", _table([1, 2]), AsyncMock())


@pytest.mark.asyncio
async def test_noop_on_empty_chunk():
    manager = _RecordingManager()
    await persist_keyset_resume_state(manager, "id", _table([]), AsyncMock())  # type: ignore[arg-type]
    assert manager.saved == []


@pytest.mark.asyncio
async def test_noop_when_column_missing_from_chunk():
    manager = _RecordingManager()
    await persist_keyset_resume_state(manager, "other", _table([1, 2]), AsyncMock())  # type: ignore[arg-type]
    assert manager.saved == []
