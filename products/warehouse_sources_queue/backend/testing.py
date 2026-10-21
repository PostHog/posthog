"""Shared test helpers for suites that exercise the queue tables.

Tests run against the default Django test database, not the dedicated queue
database: the product migration only applies to the real queue DB, so suites
create the tables here with DDL that mirrors ``migrations/``. Keep the two in
sync when the schema changes.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar, assert_never
from uuid import uuid4

from django.db import connection

import psycopg
from psycopg.rows import dict_row

from products.warehouse_sources_queue.backend.core.batch_consumer import MAX_ATTEMPTS
from products.warehouse_sources_queue.backend.core.generic_jobs import (
    JOB_LEASE_TABLE,
    JOB_STATUS_TABLE,
    JOB_TABLE,
    RETRY_REASON_KEY,
    TERMINAL_JOB_STATES,
    Job,
    JobsTable,
)
from products.warehouse_sources_queue.backend.core.job_steps import JOB_STEP_TABLE, JobStepsTable, StepRecord, StepState
from products.warehouse_sources_queue.backend.core.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
)
from products.warehouse_sources_queue.backend.core.scheduler_state import (
    SCHEDULER_DECISION_TABLE,
    SCHEDULER_STATE_TABLE,
)
from products.warehouse_sources_queue.backend.sdk.jobs import Fail, JobContext, Outcome, Retry, Success
from products.warehouse_sources_queue.backend.sdk.workflows import STARTED_STEP_KEY, WorkflowDefinition, WorkflowHandler

P = TypeVar("P")


def get_test_database_url() -> str:
    s = connection.settings_dict
    host = s.get("HOST", "localhost") or "localhost"
    port = s.get("PORT", "5432") or "5432"
    return f"postgres://{s['USER']}:{s['PASSWORD']}@{host}:{port}/{s['NAME']}"


def ensure_queue_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {BATCH_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            source_id VARCHAR(200) NOT NULL,
            job_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            s3_path TEXT NOT NULL,
            row_count INT NOT NULL,
            byte_size BIGINT NOT NULL,
            is_final_batch BOOLEAN NOT NULL,
            total_batches INT,
            total_rows BIGINT,
            sync_type VARCHAR(32) NOT NULL,
            cumulative_row_count BIGINT NOT NULL DEFAULT 0,
            resource_name VARCHAR(400) NOT NULL,
            is_resume BOOLEAN NOT NULL DEFAULT FALSE,
            is_first_ever_sync BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            destination_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Self-heal pre-existing test DBs where CREATE TABLE IF NOT EXISTS is a no-op.
    conn.execute(f"""
        ALTER TABLE {BATCH_TABLE}
            ADD COLUMN IF NOT EXISTS latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS latest_attempt SMALLINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS superseded BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS destination_ids JSONB NOT NULL DEFAULT '[]'::jsonb
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_claimable_idx ON {BATCH_TABLE} (team_id, created_at, batch_index)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_run_gate_idx ON {BATCH_TABLE} (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_schema_busy_idx ON {BATCH_TABLE} (team_id, schema_id)
            WHERE latest_state = 'executing'
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_failed_changed_idx ON {BATCH_TABLE} (state_changed_at)
            WHERE latest_state = 'failed'
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS sb_job_id_idx ON {BATCH_TABLE} (job_id)")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sbs_batch_id_desc_state_idx
            ON {STATUS_TABLE} (batch_id, created_at DESC, id DESC, job_state)
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {LEASE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sgl_team_schema_uniq UNIQUE (team_id, schema_id)
        )
    """)
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def truncate_queue_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {STATUS_TABLE}, {BATCH_TABLE}, {LEASE_TABLE} RESTART IDENTITY CASCADE")


BATCH_DEFAULTS: dict[str, Any] = {
    "team_id": 1,
    "schema_id": "schema-1",
    "source_id": "source-1",
    "job_id": "job-1",
    "run_uuid": "run-1",
    "batch_index": 0,
    "s3_path": "s3://bucket/path",
    "row_count": 100,
    "byte_size": 1024,
    "is_final_batch": False,
    "total_batches": None,
    "total_rows": None,
    "sync_type": "full_refresh",
    "cumulative_row_count": 0,
    "resource_name": "test_resource",
    "is_resume": False,
    "is_first_ever_sync": False,
    "metadata": {},
}


async def insert_batch(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    params = {**BATCH_DEFAULTS, **overrides}
    return await BatchQueue.insert(conn, **params)


def ensure_generic_job_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind VARCHAR(100) NOT NULL,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            team_id BIGINT NOT NULL,
            run_id VARCHAR(200),
            sequence INT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            priority SMALLINT NOT NULL DEFAULT 0,
            dedup_key VARCHAR(400),
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_claimable_idx ON {JOB_TABLE} (lane, kind, team_id, created_at, sequence)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_run_gate_idx ON {JOB_TABLE} (run_id, latest_state, sequence)
            WHERE latest_state IN ('pending', 'executing', 'waiting_retry', 'failed')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_group_busy_idx ON {JOB_TABLE} (lane, group_key)
            WHERE latest_state = 'executing'
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_dedup_idx ON {JOB_TABLE} (kind, dedup_key)
            WHERE dedup_key IS NOT NULL
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_LEASE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qjl_lane_group_uniq UNIQUE (lane, group_key)
        )
    """)

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_STEP_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL,
            job_created_at TIMESTAMPTZ NOT NULL,
            step_key VARCHAR(200) NOT NULL,
            state VARCHAR(16) NOT NULL,
            job_attempt SMALLINT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ NOT NULL,
            result JSONB,
            error TEXT
        )
    """)
    conn.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS qjstep_completed_uniq ON {JOB_STEP_TABLE} (job_id, job_created_at, step_key)
            WHERE state IN ('succeeded', 'skipped')
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS qjstep_job_key_idx ON {JOB_STEP_TABLE} (job_id, step_key)")


def truncate_generic_job_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        f"TRUNCATE {JOB_STEP_TABLE}, {JOB_STATUS_TABLE}, {JOB_TABLE}, {JOB_LEASE_TABLE} RESTART IDENTITY CASCADE"
    )


JOB_DEFAULTS: dict[str, Any] = {
    "kind": "test.kind",
    "lane": "test",
    "group_key": "1:group-1",
    "team_id": 1,
    "payload": {},
}


def ensure_scheduler_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEDULER_STATE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(100) NOT NULL,
            schedule_key VARCHAR(200) NOT NULL,
            team_id BIGINT NOT NULL,
            interval_seconds BIGINT NOT NULL,
            offset_seconds INT NOT NULL,
            next_due_at TIMESTAMPTZ NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qss_kind_key_uniq UNIQUE (kind, schedule_key)
        )
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS qss_next_due_idx ON {SCHEDULER_STATE_TABLE} (next_due_at)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS qss_refreshed_idx ON {SCHEDULER_STATE_TABLE} (refreshed_at)")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEDULER_DECISION_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            kind VARCHAR(100) NOT NULL,
            schedule_key VARCHAR(200) NOT NULL,
            window_boundary TIMESTAMPTZ NOT NULL,
            due_at TIMESTAMPTZ NOT NULL,
            decision VARCHAR(32) NOT NULL,
            interval_seconds BIGINT NOT NULL,
            late_seconds DOUBLE PRECISION NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qsd_kind_key_due_uniq UNIQUE (kind, schedule_key, due_at)
        )
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS qsd_observed_at_idx ON {SCHEDULER_DECISION_TABLE} (observed_at)")
    conn.execute(f"ALTER TABLE {SCHEDULER_DECISION_TABLE} ADD COLUMN IF NOT EXISTS job_id UUID")


def truncate_scheduler_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}, {SCHEDULER_STATE_TABLE} RESTART IDENTITY CASCADE")


class SimulatedCrash(BaseException):
    """A pod death just after a step's checkpoint. ``WorkflowTestRunner(crash_after=...)`` raises it.

    A ``BaseException``, like a real cancellation, so workflow code that catches ``Exception``
    does not catch it.
    """


class FakeClock:
    """A clock for workflow tests: ``sleep`` moves the time on at once and records the delay.

    Each read also moves the time on by one microsecond, so step records keep their order.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        self._now += timedelta(microseconds=1)
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(timedelta(seconds=seconds))


class WorkflowTestRunner(Generic[P]):
    """Runs a workflow in-process against the test database, one job attempt at a time.

    The runner enqueues one job for ``payload``. Each ``run()`` is one attempt of that job, with
    the status writes that the engine makes around a handler, so the step store and its fence
    behave as in production. Call ``ensure_generic_job_tables`` first.

    - ``overrides`` replaces a step's function by step key, for example a fake extraction.
    - ``crash_after`` raises ``SimulatedCrash`` just after that step's checkpoint, the first time
      the step completes. The next ``run()`` is the attempt after the recovery sweep.
    - ``calls`` counts the executions of each step, so a test sees which steps ran again.
    - ``steps`` is the newest record of each step after the last attempt.
    """

    def __init__(
        self,
        definition: WorkflowDefinition[P],
        payload: P,
        *,
        overrides: Mapping[str, Callable[..., Awaitable[Any]]] | None = None,
        crash_after: str | None = None,
        clock: FakeClock | None = None,
        database_url: str | None = None,
        team_id: int = 1,
        group_key: str | None = None,
    ) -> None:
        self.definition = definition
        self.payload = payload
        self.clock = clock or FakeClock()
        self.calls: Counter[str] = Counter()
        self.records: list[StepRecord] = []
        self.shutdown_event = asyncio.Event()
        self.job: Job | None = None
        self._overrides = dict(overrides or {})
        self._crash_after = crash_after
        self._crashed = False
        self._database_url = database_url or get_test_database_url()
        self._team_id = team_id
        self._group_key = group_key or f"{team_id}:{uuid4()}"
        self._job_id: str | None = None

    @property
    def steps(self) -> dict[str, StepRecord]:
        latest: dict[str, StepRecord] = {}
        for record in self.records:
            if record.key != STARTED_STEP_KEY:
                latest[record.key] = record
        return latest

    async def run(self) -> Outcome:
        """Run the next attempt of the job and return its outcome."""
        async with await psycopg.AsyncConnection.connect(self._database_url, autocommit=True) as conn:
            job = await self._start_attempt(conn)
            self.job = job
            handler = WorkflowHandler(self.definition, clock=self.clock, hooks=self)
            context = JobContext(
                logger=logging.getLogger(__name__),
                shutdown_event=self.shutdown_event,
                database_url=self._database_url,
                max_attempts=MAX_ATTEMPTS,
                lease_owner="workflow-test-runner",
            )
            try:
                outcome = await handler.handle(job, context)
            finally:
                self.records = await JobStepsTable.load(conn, job_id=job.id, job_created_at=job.created_at)
            await self._finish_attempt(conn, job, outcome)
        return outcome

    async def run_until_done(self, *, max_attempts: int = 20) -> Outcome:
        """Run attempts through retries and simulated crashes, and return the final outcome."""
        for _ in range(max_attempts):
            try:
                outcome = await self.run()
            except SimulatedCrash:
                continue
            if not isinstance(outcome, Retry):
                return outcome
        raise AssertionError(f"the workflow did not finish in {max_attempts} attempts")

    def resolve(self, key: str, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        self.calls[key] += 1
        return self._overrides.get(key, fn)

    def recorded(self, record: StepRecord) -> None:
        if record.key == self._crash_after and record.state is StepState.SUCCEEDED and not self._crashed:
            self._crashed = True
            raise SimulatedCrash(f"simulated crash after step {record.key!r}")

    async def _load_job(self, conn: psycopg.AsyncConnection[Any]) -> Job:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT id, kind, lane, group_key, team_id, run_id, sequence, payload, priority, dedup_key,
                       latest_state, latest_attempt, state_changed_at, created_at
                FROM {JOB_TABLE} WHERE id = %(id)s
                """,
                {"id": self._job_id},
            )
            row = await cur.fetchone()
        assert row is not None
        return Job(**{**row, "id": str(row["id"])})

    async def _start_attempt(self, conn: psycopg.AsyncConnection[Any]) -> Job:
        if self._job_id is None:
            self._job_id = await JobsTable.insert(
                conn,
                kind=self.definition.kind,
                lane=self.definition.lane,
                group_key=self._group_key,
                team_id=self._team_id,
                payload=self.definition.encode_payload(self.payload),
            )
        job = await self._load_job(conn)
        if job.latest_state in TERMINAL_JOB_STATES:
            raise AssertionError(f"the job already ended as {job.latest_state}")
        if job.latest_state == "executing":
            # The last attempt crashed. The recovery sweep re-queues the job before the next claim.
            await JobsTable.update_status(
                conn,
                job_id=job.id,
                job_state="waiting_retry",
                attempt=job.latest_attempt,
                job_created_at=job.created_at,
            )
            job = await self._load_job(conn)
        await JobsTable.update_status(
            conn, job_id=job.id, job_state="executing", attempt=job.latest_attempt + 1, job_created_at=job.created_at
        )
        # The engine gives the handler the job as it was claimed, before the executing write.
        return job

    async def _finish_attempt(self, conn: psycopg.AsyncConnection[Any], job: Job, outcome: Outcome) -> None:
        state: str
        error_response: dict[str, Any] | None
        match outcome:
            case Success():
                state, error_response = "succeeded", None
            case Fail(reason=reason):
                state, error_response = "failed", {"error": reason}
            case Retry(reason=reason, tag=tag):
                state, error_response = "waiting_retry", {"error": reason, RETRY_REASON_KEY: tag}
            case _:
                assert_never(outcome)
        await JobsTable.update_status(
            conn,
            job_id=job.id,
            job_state=state,
            attempt=job.latest_attempt + 1,
            error_response=error_response,
            job_created_at=job.created_at,
        )
