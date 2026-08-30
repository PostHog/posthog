import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import (
    RESUMABLE_STATE_TTL_SECONDS,
    ResumableSourceManager,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

RESUMABLE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable"


@dataclasses.dataclass
class _Cursor:
    next_url: str


def _inputs(
    *,
    source_id: str = "source-1",
    schema_id: str = "schema-1",
    job_id: str = "job-1",
    reset_pipeline: bool = False,
) -> SourceInputs:
    return SourceInputs(
        schema_name="quiz_attempts",
        schema_id=schema_id,
        source_id=source_id,
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id=job_id,
        logger=MagicMock(),
        reset_pipeline=reset_pipeline,
    )


class _FakeRedis:
    """In-memory stand-in that records the TTL passed to the last `set`."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.last_set_ex: int | None = None

    def ping(self) -> None:
        return None

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = value
        self.last_set_ex = ex

    def get(self, key: str) -> Any:
        return self.store.get(key)

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def redis() -> Iterator[_FakeRedis]:
    fake = _FakeRedis()
    with (
        patch(f"{RESUMABLE_MODULE}.get_client", return_value=fake),
        patch(f"{RESUMABLE_MODULE}.settings") as settings_mock,
    ):
        settings_mock.DATA_WAREHOUSE_REDIS_HOST = "localhost"
        settings_mock.DATA_WAREHOUSE_REDIS_PORT = 6379
        yield fake


def _manager(inputs: SourceInputs) -> ResumableSourceManager[_Cursor]:
    return ResumableSourceManager(inputs, _Cursor)


class TestResumableSourceManager:
    def test_state_survives_a_new_job_id(self, redis: _FakeRedis) -> None:
        # A run saves a checkpoint, then is killed. The restart is a fresh ExternalDataJob, so it
        # carries a new job_id but the same team, source, and schema. It must resume, not re-walk.
        _manager(_inputs(job_id="job-1")).save_state(_Cursor(next_url="page-2"))

        restarted = _manager(_inputs(job_id="job-2"))
        assert restarted.can_resume() is True
        assert restarted.load_state() == _Cursor(next_url="page-2")

    def test_state_is_isolated_per_schema(self, redis: _FakeRedis) -> None:
        _manager(_inputs(schema_id="schema-a")).save_state(_Cursor(next_url="a"))

        assert _manager(_inputs(schema_id="schema-b")).can_resume() is False

    def test_reset_run_never_resumes_or_persists(self, redis: _FakeRedis) -> None:
        # A prior run left a checkpoint under the now-stable key.
        _manager(_inputs()).save_state(_Cursor(next_url="page-2"))

        reset = _manager(_inputs(reset_pipeline=True))
        # A reset wipes the table, so resuming would stitch new rows onto nothing and truncate.
        assert reset.can_resume() is False
        assert reset.load_state() is None

        reset.save_state(_Cursor(next_url="page-9"))
        assert redis.get(reset._key) == '{"next_url":"page-2"}'  # untouched by the reset run

    def test_reset_run_discards_stale_state(self, redis: _FakeRedis) -> None:
        # A prior killed run left a checkpoint under the now-stable key. A reset wipes the table, so
        # the checkpoint must be dropped or a later non-reset run would resume onto the wiped table.
        _manager(_inputs()).save_state(_Cursor(next_url="page-2"))

        _manager(_inputs(reset_pipeline=True)).discard_stale_state_on_reset()

        # The next normal run finds no checkpoint and starts from the first page.
        assert _manager(_inputs()).can_resume() is False

    def test_discard_stale_state_is_noop_off_reset(self, redis: _FakeRedis) -> None:
        # A normal run calls this too; it must not wipe the checkpoint it is about to resume from.
        _manager(_inputs()).save_state(_Cursor(next_url="page-2"))

        _manager(_inputs()).discard_stale_state_on_reset()

        assert _manager(_inputs()).can_resume() is True

    def test_save_state_ttl_outlives_a_worst_case_run(self, redis: _FakeRedis) -> None:
        _manager(_inputs()).save_state(_Cursor(next_url="page-2"))

        # The import activity can run a week; the checkpoint must outlast it.
        assert redis.last_set_ex == RESUMABLE_STATE_TTL_SECONDS
        assert redis.last_set_ex > 60 * 60 * 24 * 7
