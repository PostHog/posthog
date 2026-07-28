import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

import psycopg
import fakeredis

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import sync_lock
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    DUCKGRES_LEASE_TABLE,
    DUCKGRES_STATUS_TABLE,
)

# The duckgres test module's DDL is a superset of the delta queue's (both status
# and lease tables), which the --sink duckgres tests need.
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.test_jobs_db import (
    _BATCH_DEFAULTS,
    _ensure_tables,
    _get_test_database_url,
    _truncate_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    STATUS_TABLE,
)

pytestmark = [pytest.mark.django_db]

COMMAND_MODULE = "products.warehouse_sources.backend.management.commands.manage_warehouse_queue"


@pytest.fixture(autouse=True)
def _keep_test_connection():
    # The reused consumer fail path calls close_old_connections(), which closes the
    # pytest-django test connection out from under the test transaction.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.close_old_connections"
    ):
        yield


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


@pytest.fixture
def team_2(organization):
    return create_team(organization=organization)


@pytest.fixture
def queue_conn() -> Generator[psycopg.Connection[Any]]:
    url = _get_test_database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        _ensure_tables(conn)
        _truncate_tables(conn)
        with patch(f"{COMMAND_MODULE}.WAREHOUSE_SOURCES_DATABASE_URL", url):
            yield conn


@pytest.fixture
def fake_redis() -> Generator[fakeredis.FakeRedis]:
    client = fakeredis.FakeRedis()

    @contextmanager
    def _fake_client():
        yield client

    with patch.object(sync_lock, "_get_redis_client", _fake_client):
        yield client


def _create_pipeline(
    team, source_type: str = "Stripe"
) -> tuple[ExternalDataSource, ExternalDataSchema, ExternalDataJob]:
    source = ExternalDataSource.objects.create(team=team, source_type=source_type, job_inputs={})
    schema = ExternalDataSchema.objects.create(
        name="test_table",
        team=team,
        source=source,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        status=ExternalDataSchema.Status.RUNNING,
    )
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        pipeline_version=ExternalDataJob.PipelineVersion.V3,
        workflow_id=f"workflow-{schema.id}",
        workflow_run_id=str(uuid4()),
    )
    return source, schema, job


def _insert_batch(conn: psycopg.Connection[Any], *, age_hours: float = 0, **overrides: Any) -> str:
    params = {**_BATCH_DEFAULTS, **overrides}
    params["metadata"] = json.dumps(params["metadata"])
    params["age_seconds"] = age_hours * 3600
    row = conn.execute(
        f"""
        INSERT INTO {BATCH_TABLE} (
            id, team_id, schema_id, source_id, job_id, run_uuid, batch_index, s3_path,
            row_count, byte_size, is_final_batch, total_batches, total_rows, sync_type,
            cumulative_row_count, resource_name, is_resume, is_first_ever_sync, metadata, created_at
        ) VALUES (
            gen_random_uuid(), %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
            %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
            %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
            %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s,
            now() - make_interval(secs => %(age_seconds)s)
        ) RETURNING id
        """,
        params,
    ).fetchone()
    assert row is not None
    return str(row[0])


def _set_status(
    conn: psycopg.Connection[Any], batch_id: str, state: str, *, table: str = STATUS_TABLE, age_hours: float = 0
) -> None:
    conn.execute(
        f"INSERT INTO {table} (batch_id, job_state, attempt, exec_time, created_at) "
        "VALUES (%s, %s, 0, now(), now() - make_interval(secs => %s))",
        (batch_id, state, age_hours * 3600),
    )


def _insert_lease(
    conn: psycopg.Connection[Any], *, team_id: int, schema_id: str, live: bool, table: str = LEASE_TABLE
) -> None:
    interval = "'5 minutes'" if live else "'-5 minutes'"
    conn.execute(
        f"INSERT INTO {table} (team_id, schema_id, owner_token, expires_at, acquired_at, updated_at) "
        f"VALUES (%s, %s, %s, now() + interval {interval}, now(), now())",
        (team_id, schema_id, str(uuid4())),
    )


def _lease_count(conn: psycopg.Connection[Any], schema_id: str, *, table: str = LEASE_TABLE) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE schema_id = %s", (schema_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _failed_status_counts_by_run(conn: psycopg.Connection[Any], *, table: str = STATUS_TABLE) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT b.run_uuid, COUNT(*)
        FROM {table} s JOIN {BATCH_TABLE} b ON b.id = s.batch_id
        WHERE s.job_state = 'failed'
        GROUP BY b.run_uuid
        """
    ).fetchall()
    return {run_uuid: int(n) for run_uuid, n in rows}


def _seed_active_run(
    conn: psycopg.Connection[Any],
    *,
    team,
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    run_uuid: str,
    age_hours: float = 0,
) -> dict[str, str]:
    """One succeeded batch and two pending ones (unclaimed + executing), like a mid-load run."""
    common = {
        "team_id": team.pk,
        "schema_id": str(schema.id),
        "source_id": str(schema.source_id),
        "job_id": str(job.id),
        "run_uuid": run_uuid,
        "metadata": {"workflow_run_id": job.workflow_run_id},
        "age_hours": age_hours,
    }
    succeeded = _insert_batch(conn, **common, batch_index=0)
    _set_status(conn, succeeded, "succeeded", age_hours=age_hours)
    executing = _insert_batch(conn, **common, batch_index=1)
    _set_status(conn, executing, "executing", age_hours=age_hours)
    unclaimed = _insert_batch(conn, **common, batch_index=2)
    return {"succeeded": succeeded, "executing": executing, "unclaimed": unclaimed}


def _call(*args: str) -> str:
    out = StringIO()
    call_command("manage_warehouse_queue", *args, stdout=out)
    return out.getvalue()


class TestFailRun:
    def test_live_run_fails_pending_batches_job_lease_and_redis_lock(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)
        assert job.workflow_run_id is not None
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(schema.id), job.workflow_run_id)

        out = _call("fail-run", "--team-id", str(team.pk), "--schema-id", str(schema.id), "--live-run", "--yes")

        # only the executing + unclaimed batches get a failed status, not the succeeded one
        assert _failed_status_counts_by_run(queue_conn) == {run_uuid: 2}
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert _lease_count(queue_conn, str(schema.id)) == 0
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(schema.id)) is None
        assert "marked 2 pending batch(es) failed" in out

    def test_dry_run_mutates_nothing(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)
        assert job.workflow_run_id is not None
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(schema.id), job.workflow_run_id)

        out = _call("fail-run", "--team-id", str(team.pk), "--schema-id", str(schema.id))

        assert "Dry run" in out
        assert _failed_status_counts_by_run(queue_conn) == {}
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING
        assert _lease_count(queue_conn, str(schema.id)) == 1
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(schema.id)) == job.workflow_run_id

    def test_source_type_only_touches_only_matching_runs(self, team, team_2, queue_conn, fake_redis):
        _, stripe_schema, stripe_job = _create_pipeline(team, source_type="Stripe")
        _, pg_schema, pg_job = _create_pipeline(team_2, source_type="Postgres")
        stripe_run, pg_run = str(uuid4()), str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=stripe_schema, job=stripe_job, run_uuid=stripe_run)
        _seed_active_run(queue_conn, team=team_2, schema=pg_schema, job=pg_job, run_uuid=pg_run)

        _call("fail-run", "--source-type", "stripe", "--live-run", "--yes")

        assert _failed_status_counts_by_run(queue_conn) == {stripe_run: 2}
        stripe_job.refresh_from_db()
        pg_job.refresh_from_db()
        assert stripe_job.status == ExternalDataJob.Status.FAILED
        assert pg_job.status == ExternalDataJob.Status.RUNNING

    def test_max_runs_cap_aborts(self, team, queue_conn, fake_redis):
        for _ in range(2):
            _, schema, job = _create_pipeline(team)
            _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=str(uuid4()))

        with pytest.raises(CommandError, match="--max-runs"):
            _call("fail-run", "--team-id", str(team.pk), "--max-runs", "1", "--live-run", "--yes")

        assert _failed_status_counts_by_run(queue_conn) == {}

    @pytest.mark.parametrize("force", [False, True], ids=["without_force", "with_force"])
    def test_live_lease_deleted_only_with_force(self, force, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=str(uuid4()))
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=True)

        args = ["fail-run", "--team-id", str(team.pk), "--schema-id", str(schema.id), "--live-run", "--yes"]
        if force:
            args.append("--force")
        out = _call(*args)

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert _lease_count(queue_conn, str(schema.id)) == (0 if force else 1)
        if not force:
            assert "Use --force" in out

    def test_fails_running_job_with_no_queue_batches(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)

        _call("fail-run", "--team-id", str(team.pk), "--schema-id", str(schema.id), "--live-run", "--yes")

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED

    def test_cancel_workflow_connects_with_overrides_and_cancels(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=str(uuid4()))
        handle = MagicMock(cancel=AsyncMock())
        client = MagicMock(**{"get_workflow_handle.return_value": handle})
        connect_mock = AsyncMock(return_value=client)

        with patch("posthog.temporal.common.client.connect", connect_mock):
            out = _call(
                "fail-run",
                "--team-id",
                str(team.pk),
                "--schema-id",
                str(schema.id),
                "--cancel-workflow",
                "--temporal-host",
                "temporal-fe.internal",
                "--live-run",
                "--yes",
            )

        assert connect_mock.call_args.args[0] == "temporal-fe.internal"
        client.get_workflow_handle.assert_called_once_with(job.workflow_id)
        handle.cancel.assert_awaited_once()
        assert f"cancellation requested for {job.workflow_id}" in out

    def test_only_stuck_fails_only_inactive_runs_and_allows_unscoped_use(self, team, queue_conn, fake_redis):
        # a wedged run: last queue activity 8h ago (past the 6h default grace)
        _, stale_schema, stale_job = _create_pipeline(team)
        stale_run = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=stale_schema, job=stale_job, run_uuid=stale_run, age_hours=8)
        # a healthy run: activity just now
        _, fresh_schema, fresh_job = _create_pipeline(team)
        fresh_run = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=fresh_schema, job=fresh_job, run_uuid=fresh_run)
        # job-only targets (nothing in the queue): one old, one just started
        _, _, stale_orphan_job = _create_pipeline(team)
        ExternalDataJob.objects.filter(id=stale_orphan_job.id).update(created_at=timezone.now() - timedelta(hours=8))
        _, _, fresh_orphan_job = _create_pipeline(team)

        out = _call("fail-run", "--only-stuck", "--live-run", "--yes")

        assert _failed_status_counts_by_run(queue_conn) == {stale_run: 2}
        for job, expected in [
            (stale_job, ExternalDataJob.Status.FAILED),
            (stale_orphan_job, ExternalDataJob.Status.FAILED),
            (fresh_job, ExternalDataJob.Status.RUNNING),
            (fresh_orphan_job, ExternalDataJob.Status.RUNNING),
        ]:
            job.refresh_from_db()
            assert job.status == expected
        assert "skipped 2 run(s)" in out


class TestTargetingValidation:
    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["fail-run", "--schema-id", "x"], id="schema_without_team"),
            pytest.param(["fail-run", "--source-id", "x"], id="source_without_team"),
            pytest.param(["fail-run", "--run-uuid", "x", "--team-id", "1"], id="run_uuid_combined"),
            pytest.param(["fail-run"], id="fail_run_unscoped"),
            pytest.param(["release-locks"], id="release_locks_unscoped"),
            pytest.param(["release-locks", "--run-uuid", "x"], id="release_locks_run_uuid"),
            pytest.param(
                ["release-locks", "--team-id", "1", "--leases-only", "--redis-only"], id="release_both_only_flags"
            ),
            pytest.param(
                ["fail-run", "--sink", "duckgres", "--team-id", "1", "--cancel-workflow"],
                id="cancel_workflow_duckgres",
            ),
            pytest.param(
                ["release-locks", "--sink", "duckgres", "--team-id", "1", "--redis-only"], id="redis_only_duckgres"
            ),
        ],
    )
    def test_invalid_targeting_raises(self, args, queue_conn, fake_redis):
        with pytest.raises(CommandError):
            _call(*args)


class TestReleaseLocks:
    def test_live_lease_requires_force_and_stale_state_is_released(self, team, queue_conn, fake_redis):
        source = ExternalDataSource.objects.create(team=team, source_type="Stripe", job_inputs={})
        live_schema = ExternalDataSchema.objects.create(
            name="live", team=team, source=source, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
        )
        stale_schema = ExternalDataSchema.objects.create(
            name="stale", team=team, source=source, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
        )
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(live_schema.id), live=True)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(stale_schema.id), live=False)
        # a stale redis lock: held by a token that matches no Running job
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(stale_schema.id), "dead-workflow-run")

        out = _call("release-locks", "--team-id", str(team.pk), "--live-run", "--yes")

        assert "LIVE" in out
        assert _lease_count(queue_conn, str(stale_schema.id)) == 0
        assert _lease_count(queue_conn, str(live_schema.id)) == 1  # live lease kept without --force
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(stale_schema.id)) is None

        _call("release-locks", "--team-id", str(team.pk), "--live-run", "--yes", "--force")
        assert _lease_count(queue_conn, str(live_schema.id)) == 0


class TestStatus:
    def test_status_reports_all_sections_without_error(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        batches = _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _set_status(queue_conn, batches["executing"], "executing")  # ensure stale-executing section has data
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)

        out = _call("status", "--team-id", str(team.pk), "--stale-grace-seconds", "0")

        assert run_uuid in out
        assert str(schema.id) in out
        assert "unclaimed: 1" in out


def _seed_duckgres_run(
    conn: psycopg.Connection[Any],
    *,
    team,
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    run_uuid: str,
) -> dict[str, str]:
    """A run mid-way through the duckgres sink: one batch fully applied, one the
    sink hasn't claimed, one retrying, and one whose delta load isn't done yet."""
    common = {
        "team_id": team.pk,
        "schema_id": str(schema.id),
        "source_id": str(schema.source_id),
        "job_id": str(job.id),
        "run_uuid": run_uuid,
        "metadata": {"workflow_run_id": job.workflow_run_id},
    }
    applied = _insert_batch(conn, **common, batch_index=0)
    _set_status(conn, applied, "succeeded")
    _set_status(conn, applied, "succeeded", table=DUCKGRES_STATUS_TABLE)
    unclaimed = _insert_batch(conn, **common, batch_index=1)
    _set_status(conn, unclaimed, "succeeded")
    retrying = _insert_batch(conn, **common, batch_index=2)
    _set_status(conn, retrying, "succeeded")
    _set_status(conn, retrying, "waiting_retry", table=DUCKGRES_STATUS_TABLE)
    delta_pending = _insert_batch(conn, **common, batch_index=3)
    _set_status(conn, delta_pending, "executing")
    return {"applied": applied, "unclaimed": unclaimed, "retrying": retrying, "delta_pending": delta_pending}


class TestDuckgresSink:
    def test_fail_run_fails_pending_duckgres_batches_without_touching_delta_or_job(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_duckgres_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False, table=DUCKGRES_LEASE_TABLE)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)

        out = _call(
            "fail-run",
            "--sink",
            "duckgres",
            "--team-id",
            str(team.pk),
            "--schema-id",
            str(schema.id),
            "--live-run",
            "--yes",
        )

        # only the duckgres-pending batches (unclaimed + retrying) get duckgres failed rows;
        # the applied batch and the delta-still-executing batch stay untouched
        assert _failed_status_counts_by_run(queue_conn, table=DUCKGRES_STATUS_TABLE) == {run_uuid: 2}
        assert _failed_status_counts_by_run(queue_conn) == {}  # delta statuses untouched
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING  # the duckgres sink doesn't own the job
        assert _lease_count(queue_conn, str(schema.id), table=DUCKGRES_LEASE_TABLE) == 0
        assert _lease_count(queue_conn, str(schema.id)) == 1  # delta lease untouched
        assert "marked 2 pending batch(es) failed" in out

    def test_release_locks_releases_only_duckgres_leases(self, team, queue_conn, fake_redis):
        _, schema, _ = _create_pipeline(team)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False, table=DUCKGRES_LEASE_TABLE)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)

        _call("release-locks", "--sink", "duckgres", "--team-id", str(team.pk), "--live-run", "--yes")

        assert _lease_count(queue_conn, str(schema.id), table=DUCKGRES_LEASE_TABLE) == 0
        assert _lease_count(queue_conn, str(schema.id)) == 1

    def test_status_reports_duckgres_sections(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        batches = _seed_duckgres_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _set_status(queue_conn, batches["retrying"], "executing", table=DUCKGRES_STATUS_TABLE)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False, table=DUCKGRES_LEASE_TABLE)

        out = _call("status", "--sink", "duckgres", "--team-id", str(team.pk), "--stale-grace-seconds", "0")

        assert run_uuid in out
        assert "unclaimed: 1" in out  # delta-succeeded batch the duckgres sink hasn't claimed
        assert "Redis pipeline locks" not in out  # delta-only section
