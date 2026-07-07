from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import StringIO
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

import psycopg
import fakeredis
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionResponse
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import sync_lock
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
    _ensure_tables,
    _get_test_database_url,
    _truncate_tables,
)
from products.warehouse_sources.backend.tests.management.test_manage_warehouse_queue import (
    _failed_status_counts_by_run,
    _seed_active_run,
)

pytestmark = [pytest.mark.django_db]

COMMAND_MODULE = "products.warehouse_sources.backend.management.commands.unstick_external_data_jobs"
CUTOFF = "2026-07-02T00:00:00Z"
BEFORE_CUTOFF = datetime(2026, 7, 1, tzinfo=UTC)
AFTER_CUTOFF = datetime(2026, 7, 3, tzinfo=UTC)


class FakeTemporal:
    def __init__(self) -> None:
        self.describe_results: dict[str, Any] = {}
        self.terminated: list[str] = []

    def get_workflow_handle(self, workflow_id: str, run_id: str | None = None) -> "FakeHandle":
        return FakeHandle(self, run_id or "")


class FakeHandle:
    def __init__(self, temporal: FakeTemporal, run_id: str) -> None:
        self._temporal = temporal
        self._run_id = run_id

    async def describe(self) -> Any:
        result = self._temporal.describe_results[self._run_id]
        if isinstance(result, Exception):
            raise result
        return result

    async def terminate(self, reason: str | None = None) -> None:
        self._temporal.terminated.append(self._run_id)


def _desc(status: WorkflowExecutionStatus, wft_attempt: int | None = None) -> Any:
    raw = DescribeWorkflowExecutionResponse()
    if wft_attempt is not None:
        raw.pending_workflow_task.attempt = wft_attempt
    return SimpleNamespace(status=status, raw_description=raw)


def _wedged() -> Any:
    return _desc(WorkflowExecutionStatus.RUNNING, wft_attempt=50)


def _healthy() -> Any:
    return _desc(WorkflowExecutionStatus.RUNNING)


def _terminated() -> Any:
    return _desc(WorkflowExecutionStatus.TERMINATED)


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


@pytest.fixture
def fake_temporal() -> Generator[FakeTemporal]:
    temporal = FakeTemporal()
    with patch(f"{COMMAND_MODULE}.sync_connect", return_value=temporal):
        yield temporal


@pytest.fixture
def trigger_mock() -> Generator[MagicMock]:
    with patch(f"{COMMAND_MODULE}.trigger_external_data_workflow") as mock:
        yield mock


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


def _create_stuck_job(
    team,
    *,
    pipeline_version: str = ExternalDataJob.PipelineVersion.V2,
    created_at: datetime = BEFORE_CUTOFF,
    schema_status: str = ExternalDataSchema.Status.RUNNING,
    should_sync: bool = True,
) -> tuple[ExternalDataSchema, ExternalDataJob]:
    source = ExternalDataSource.objects.create(team=team, source_type="Stripe", job_inputs={})
    schema = ExternalDataSchema.objects.create(
        name="test_table",
        team=team,
        source=source,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        status=schema_status,
        should_sync=should_sync,
    )
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        pipeline_version=pipeline_version,
        workflow_id=f"workflow-{schema.id}",
        workflow_run_id=str(uuid4()),
    )
    ExternalDataJob.objects.filter(id=job.id).update(created_at=created_at)
    job.refresh_from_db()
    return schema, job


def _call(*args: str) -> str:
    out = StringIO()
    call_command("unstick_external_data_jobs", "--created-before", CUTOFF, *args, stdout=out)
    return out.getvalue()


class TestClassificationOutcomes:
    @pytest.mark.parametrize(
        "describe_result,expect_failed,expect_terminated",
        [
            pytest.param(_wedged(), True, True, id="wedged_is_terminated_and_failed"),
            pytest.param(_terminated(), True, False, id="already_terminal_fixed_without_terminate"),
            pytest.param(
                RPCError("not found", RPCStatusCode.NOT_FOUND, b""),
                True,
                False,
                id="gone_out_of_retention_fixed_without_terminate",
            ),
            pytest.param(_healthy(), False, False, id="healthy_is_skipped"),
            pytest.param(RPCError("boom", RPCStatusCode.UNAVAILABLE, b""), False, False, id="ambiguous_is_skipped"),
        ],
    )
    def test_only_wedged_or_terminal_jobs_are_fixed(
        self, describe_result, expect_failed, expect_terminated, team, fake_temporal, queue_conn
    ):
        schema, job = _create_stuck_job(team)
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = describe_result

        _call("--live-run", "--yes")

        job.refresh_from_db()
        schema.refresh_from_db()
        if expect_failed:
            assert job.status == ExternalDataJob.Status.FAILED
            assert job.finished_at is not None
            assert job.latest_error is not None
            assert schema.status == ExternalDataSchema.Status.FAILED
        else:
            assert job.status == ExternalDataJob.Status.RUNNING
            assert schema.status == ExternalDataSchema.Status.RUNNING
        assert fake_temporal.terminated == ([job.workflow_run_id] if expect_terminated else [])

    def test_terminate_healthy_flag_sweeps_healthy_workflows(self, team, fake_temporal, queue_conn):
        schema, job = _create_stuck_job(team)
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = _healthy()

        _call("--live-run", "--yes", "--terminate-healthy")

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert fake_temporal.terminated == [job.workflow_run_id]


class TestSafetyRails:
    def test_dry_run_mutates_nothing(self, team, fake_temporal):
        schema, job = _create_stuck_job(team)
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = _wedged()

        out = _call()

        assert "Dry run" in out
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING
        assert fake_temporal.terminated == []

    def test_job_created_after_cutoff_is_ignored(self, team, fake_temporal):
        _, job = _create_stuck_job(team, created_at=AFTER_CUTOFF)

        out = _call()

        assert "No Running jobs match" in out
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING

    def test_max_jobs_cap_aborts_before_any_write(self, team, fake_temporal, queue_conn):
        _, job_a = _create_stuck_job(team)
        _, job_b = _create_stuck_job(team)

        with pytest.raises(CommandError, match="--max-jobs"):
            _call("--live-run", "--yes", "--max-jobs", "1")

        job_a.refresh_from_db()
        job_b.refresh_from_db()
        assert job_a.status == ExternalDataJob.Status.RUNNING
        assert job_b.status == ExternalDataJob.Status.RUNNING
        assert fake_temporal.terminated == []

    def test_schema_of_recovered_sync_is_not_clobbered(self, team, fake_temporal, queue_conn, trigger_mock):
        schema, stuck_job = _create_stuck_job(team, schema_status=ExternalDataSchema.Status.COMPLETED)
        recovered_job = ExternalDataJob.objects.create(
            team=team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            pipeline_version=ExternalDataJob.PipelineVersion.V2,
        )
        assert recovered_job.created_at > stuck_job.created_at
        assert stuck_job.workflow_run_id is not None
        fake_temporal.describe_results[stuck_job.workflow_run_id] = _terminated()

        _call("--live-run", "--yes", "--trigger-sync")

        stuck_job.refresh_from_db()
        schema.refresh_from_db()
        recovered_job.refresh_from_db()
        assert stuck_job.status == ExternalDataJob.Status.FAILED
        assert schema.status == ExternalDataSchema.Status.COMPLETED
        assert recovered_job.status == ExternalDataJob.Status.COMPLETED
        trigger_mock.assert_not_called()


class TestV3Cleanup:
    def test_pending_batches_failed_and_lock_released(self, team, fake_temporal, queue_conn, fake_redis):
        schema, job = _create_stuck_job(team, pipeline_version=ExternalDataJob.PipelineVersion.V3)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        assert job.workflow_run_id is not None
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(schema.id), job.workflow_run_id)
        fake_temporal.describe_results[job.workflow_run_id] = _wedged()

        _call("--live-run", "--yes")

        assert _failed_status_counts_by_run(queue_conn) == {run_uuid: 2}
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(schema.id)) is None

    def test_lock_held_by_newer_run_is_left_in_place(self, team, fake_temporal, queue_conn, fake_redis):
        schema, job = _create_stuck_job(team, pipeline_version=ExternalDataJob.PipelineVersion.V3)
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(schema.id), "newer-run-token")
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = _wedged()

        _call("--live-run", "--yes")

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(schema.id)) == "newer-run-token"


class TestTriggerSync:
    def test_fixed_schema_is_retriggered(self, team, fake_temporal, queue_conn, trigger_mock):
        schema, job = _create_stuck_job(team)
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = _wedged()

        _call("--live-run", "--yes", "--trigger-sync")

        trigger_mock.assert_called_once()
        assert trigger_mock.call_args[0][0].id == schema.id

    @pytest.mark.parametrize(
        "setup",
        [
            pytest.param("should_sync_disabled", id="should_sync_disabled"),
            pytest.param("schema_deleted", id="schema_deleted"),
            pytest.param("team_billing_paused", id="team_billing_paused"),
        ],
    )
    def test_guarded_schemas_are_not_retriggered(self, setup, team, fake_temporal, queue_conn, trigger_mock):
        schema, job = _create_stuck_job(team, should_sync=setup != "should_sync_disabled")
        if setup == "schema_deleted":
            ExternalDataSchema.objects.filter(id=schema.id).update(deleted=True)
        elif setup == "team_billing_paused":
            ExternalDataSchema.objects.create(
                name="paused_sibling",
                team=team,
                source=schema.source,
                sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
                status=ExternalDataSchema.Status.PAUSED,
            )
        assert job.workflow_run_id is not None
        fake_temporal.describe_results[job.workflow_run_id] = _wedged()

        _call("--live-run", "--yes", "--trigger-sync")

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        trigger_mock.assert_not_called()
