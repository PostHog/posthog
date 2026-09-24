from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from fakeredis import FakeRedis
from redis.exceptions import ReadOnlyError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema_resume import (
    RESUME_TTL_SECONDS,
    ResumeCheckpoint,
    ResumeWindow,
    SchemaResumeStore,
    clear_schema_resume_state,
    schema_resume_key,
)


def _window() -> ResumeWindow:
    return ResumeWindow(
        incremental_field_last_value=10,
        sync_type="append",
        incremental_field="sequence",
        incremental_field_type="Integer",
        source_id="source-1",
    )


def _job_key(job_id: str) -> str:
    return f"posthog:data_warehouse:resumable_source:1:{job_id}"


def _store(job_id: str, *, loaded: set[int], window: ResumeWindow | None = None) -> SchemaResumeStore:
    return SchemaResumeStore(
        team_id=1,
        schema_id="schema-1",
        job_id=job_id,
        job_key=_job_key(job_id),
        window=window or _window(),
        is_durable=lambda checkpoint: checkpoint.batch_index in loaded,
        logger=MagicMock(),
    )


def _checkpoint(batch_index: int, *, job_id: str = "job-1") -> ResumeCheckpoint:
    return ResumeCheckpoint(
        cursor=f'{{"cursor":"page-{batch_index}"}}',
        high_water_mark=50,
        job_id=job_id,
        job_created_at=datetime.now(UTC) - timedelta(hours=1),
        run_uuid=f"{job_id}-run-a1",
        batch_index=batch_index,
        saved_at=datetime.now(UTC),
    )


class TestSchemaResumeStore:
    @pytest.mark.parametrize("read_only_once", [False, True])
    def test_reset_clears_namespaces_after_a_redis_failover(self, read_only_once: bool) -> None:
        redis = FakeRedis()
        root = _store("job-1", loaded={0})
        root.prepare(redis, reset_pipeline=False)
        root.commit(redis, _checkpoint(0))
        sibling = root.with_namespace("events", job_key=f"{_job_key('job-1')}:events")
        sibling.prepare(redis, reset_pipeline=False)
        sibling.commit(redis, _checkpoint(0))
        pipeline = redis.pipeline

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.schema_resume.get_client",
                return_value=redis,
            ),
            patch.object(
                redis, "pipeline", side_effect=[ReadOnlyError(), pipeline()] if read_only_once else [pipeline()]
            ),
        ):
            clear_schema_resume_state(team_id=1, schema_id="schema-1")

        assert list(redis.scan_iter(f"{schema_resume_key(1, 'schema-1')}*")) == []
        sibling.commit(redis, _checkpoint(1))
        assert list(redis.scan_iter(f"{schema_resume_key(1, 'schema-1')}*")) == []

    def test_successor_uses_the_loaded_checkpoint_and_keeps_its_window(self) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded={0})
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))

        successor = _store("job-2", loaded={0})
        successor.prepare(redis, reset_pipeline=False)

        assert redis.get(_job_key("job-2")) == b'{"cursor":"page-0"}'
        assert successor.high_water_mark == 50
        assert 0 < redis.ttl(schema_resume_key(1, "schema-1")) <= RESUME_TTL_SECONDS

    @pytest.mark.parametrize(
        "changed,reset_pipeline",
        [
            ({"incremental_field_last_value": 20}, False),
            ({"sync_type": "incremental"}, False),
            ({"incremental_field": "updated_sequence"}, False),
            ({"incremental_field_type": "String"}, False),
            ({"source_id": "source-2"}, False),
            ({"api_version": "v2"}, False),
            ({"source_config_hash": "another-connection"}, False),
            ({}, True),
        ],
    )
    def test_rejects_and_deletes_an_incompatible_checkpoint(
        self, changed: dict[str, object], reset_pipeline: bool
    ) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded={0})
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))

        successor = _store("job-2", loaded={0}, window=_window().model_copy(update=changed))
        successor.prepare(redis, reset_pipeline=reset_pipeline)

        assert not redis.exists(_job_key("job-2"))
        assert not redis.exists(schema_resume_key(1, "schema-1"))
        assert successor.high_water_mark is None

    def test_does_not_skip_batches_that_never_loaded(self) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded=set())
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))

        successor = _store("job-2", loaded=set())
        successor.prepare(redis, reset_pipeline=False)

        assert not redis.exists(_job_key("job-2"))
        assert successor.high_water_mark is None

    def test_keeps_the_confirmed_checkpoint_when_the_newest_batch_does_not_load(self) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded={0})
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))
        first.commit(redis, _checkpoint(1))

        successor = _store("job-2", loaded=set())
        successor.prepare(redis, reset_pipeline=False)

        assert redis.get(_job_key("job-2")) == b'{"cursor":"page-0"}'
        assert successor.high_water_mark == 50

    @pytest.mark.parametrize("successor_started", [False, True])
    def test_completion_clears_only_the_state_this_job_owns(self, successor_started: bool) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded={0})
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))
        if successor_started:
            successor = _store("job-2", loaded={0})
            successor.prepare(redis, reset_pipeline=False)

        first.clear(redis)

        assert not redis.exists(_job_key("job-1"))
        assert bool(redis.exists(schema_resume_key(1, "schema-1"))) == successor_started
        if successor_started:
            assert redis.get(_job_key("job-2")) == b'{"cursor":"page-0"}'

    def test_an_old_manager_cannot_restore_state_after_a_reset(self) -> None:
        redis = FakeRedis()
        first = _store("job-1", loaded={0, 1})
        first.prepare(redis, reset_pipeline=False)
        first.commit(redis, _checkpoint(0))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.schema_resume.get_client",
            return_value=redis,
        ):
            clear_schema_resume_state(team_id=1, schema_id="schema-1")
        first.commit(redis, _checkpoint(1))

        successor = _store("job-2", loaded={0, 1})
        successor.prepare(redis, reset_pipeline=False)

        assert not redis.exists(schema_resume_key(1, "schema-1"))
        assert not redis.exists(_job_key("job-2"))
