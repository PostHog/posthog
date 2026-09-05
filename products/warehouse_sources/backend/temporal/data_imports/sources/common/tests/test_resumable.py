import builtins
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


@dataclasses.dataclass(frozen=True)
class _Cursor:
    next_url: str


def _inputs(
    *,
    source_id: str = "source-1",
    schema_id: str = "schema-1",
    job_id: str = "job-1",
    reset_pipeline: bool = False,
    api_version: str | None = None,
    connection_target: str | None = None,
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
        api_version=api_version,
        connection_target=connection_target,
    )


class _FakePipeline:
    """Buffers commands until `execute`, so a forgotten `execute()` shows up as unwritten state."""

    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._queued: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def queue(*args: Any, **kwargs: Any) -> "_FakePipeline":
            self._queued.append((name, args, kwargs))
            return self

        return queue

    def execute(self) -> list[Any]:
        return [getattr(self._redis, name)(*args, **kwargs) for name, args, kwargs in self._queued]


class _FakeRedis:
    """In-memory stand-in that records the TTL passed to the last `set`.

    Deliberately offers no `scan_iter`: cleanup that walks the keyspace instead of the schema's own
    key index fails here rather than passing quietly.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.last_set_ex: int | None = None

    def ping(self) -> None:
        return None

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = value
        self.last_set_ex = ex

    def get(self, key: str) -> Any:
        return self.store.get(key)

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def delete(self, *keys: str) -> int:
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    def expire(self, key: str, seconds: int) -> bool:
        return key in self.store

    def sadd(self, key: str, *values: str) -> int:
        members: set[str] = self.store.setdefault(key, set())
        before = len(members)
        members.update(values)
        return len(members) - before

    def srem(self, key: str, *values: str) -> int:
        members = self.store.get(key)
        if not isinstance(members, set):
            return 0
        removed = len(members & set(values))
        members -= set(values)
        # Redis drops a set key once its last member is removed.
        if not members:
            del self.store[key]
        return removed

    # Qualified because this class defines a `set` method, shadowing the builtin in the class body.
    def smembers(self, key: str) -> builtins.set[str]:
        members = self.store.get(key)
        if not isinstance(members, set):
            return set()
        return {str(member) for member in members}


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

    def test_clear_all_state_removes_namespaced_siblings(self, redis: _FakeRedis) -> None:
        base = _manager(_inputs())
        base.save_state(_Cursor(next_url="base"))
        # A source that walks more than one endpoint writes namespaced siblings (Convex).
        base.with_namespace("list_snapshot").save_state(_Cursor(next_url="snapshot"))
        base.with_namespace("document_deltas").save_state(_Cursor(next_url="deltas"))

        base.clear_all_state()

        # A plain clear_state would leave the namespaced cursors behind to poison the next run.
        assert redis.store == {}

    def test_api_version_isolates_the_key(self, redis: _FakeRedis) -> None:
        _manager(_inputs(api_version="2024-01-01")).save_state(_Cursor(next_url="old"))

        # A repin cancels the running job; resuming its cursor against the new version is unsafe.
        assert _manager(_inputs(api_version="2025-01-01")).can_resume() is False

    def test_clear_all_state_removes_other_api_versions(self, redis: _FakeRedis) -> None:
        # A repin leaves version A's cursor behind. When a later run under version B walks to
        # completion and clears, version A's checkpoint must go too: otherwise a repin back to A
        # within the TTL resumes the stale cursor onto a table the run should full-refresh, silently
        # keeping only the tail. A version-scoped clear would leave the other version's key behind.
        _manager(_inputs(api_version="2024-01-01")).save_state(_Cursor(next_url="old"))

        _manager(_inputs(api_version="2025-01-01")).clear_all_state()

        assert _manager(_inputs(api_version="2024-01-01")).can_resume() is False

    def test_connection_target_isolates_the_key(self, redis: _FakeRedis) -> None:
        # Repointing a source at another host keeps the same team, source, and schema ids, so
        # without the target in the key the next run would replay the old host's cursor — usually a
        # whole URL — and stitch two upstreams into one table while skipping the new host's start.
        _manager(_inputs(connection_target="old-host")).save_state(_Cursor(next_url="https://old/page-2"))

        assert _manager(_inputs(connection_target="new-host")).can_resume() is False

    def test_clear_all_state_leaves_other_schemas_alone(self, redis: _FakeRedis) -> None:
        # Cleanup runs on every completed sync, so it must reach only the keys this schema owns. A
        # cleanup scoped any wider — a keyspace walk, or an index shared between schemas — would
        # drop a sibling schema's live cursor and silently restart its walk from the first page.
        _manager(_inputs(schema_id="schema-a")).save_state(_Cursor(next_url="a"))
        _manager(_inputs(schema_id="schema-b")).save_state(_Cursor(next_url="b"))

        _manager(_inputs(schema_id="schema-a")).clear_all_state()

        assert _manager(_inputs(schema_id="schema-a")).can_resume() is False
        assert _manager(_inputs(schema_id="schema-b")).load_state() == _Cursor(next_url="b")
