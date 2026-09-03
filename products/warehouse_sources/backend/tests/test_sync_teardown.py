from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.utils import timezone

import psycopg
import fakeredis

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_DELETED_JOB_ERROR,
    SYNC_DISABLED_JOB_ERROR,
    ExternalDataSchema,
    update_should_sync,
)
from products.warehouse_sources.backend.sync_teardown import teardown_schema_syncs
from products.warehouse_sources.backend.tasks.tasks import (
    STOPPED_SYNC_SWEEP_GRACE,
    STOPPED_SYNC_SWEEP_MAX_JOB_AGE,
    cleanup_disabled_external_data_schema,
    sweep_stopped_schema_syncs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import sync_lock
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
    _ensure_tables,
    _get_test_database_url,
    _truncate_tables,
)
from products.warehouse_sources.backend.tests.management.test_manage_warehouse_queue import (
    _create_pipeline,
    _failed_status_counts_by_run,
    _insert_lease,
    _lease_count,
    _seed_active_run,
)

pytestmark = [pytest.mark.django_db]

TASK_DELAY = "products.warehouse_sources.backend.tasks.cleanup_disabled_external_data_schema.delay"


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


def _create_schema_with_running_job(team) -> tuple[ExternalDataSchema, ExternalDataJob]:
    _, schema, job = _create_pipeline(team)
    return schema, job


class TestDisableChokepointDispatch:
    def test_save_disable_with_running_job_dispatches_teardown(self, team, django_capture_on_commit_callbacks):
        schema, _job = _create_schema_with_running_job(team)

        with patch(TASK_DELAY) as mock_delay, django_capture_on_commit_callbacks(execute=True):
            schema.should_sync = False
            schema.save()

        mock_delay.assert_called_once_with(
            team_id=team.pk,
            schema_id=str(schema.id),
            reason=SYNC_DISABLED_JOB_ERROR,
            exclude_workflow_id=None,
        )

    @pytest.mark.parametrize(
        "case",
        ["already_disabled", "no_running_job", "re_enable"],
    )
    def test_no_dispatch_without_a_real_disable_of_live_work(self, case, team, django_capture_on_commit_callbacks):
        schema, job = _create_schema_with_running_job(team)
        if case in ("already_disabled", "re_enable"):
            ExternalDataSchema.objects.filter(pk=schema.pk).update(should_sync=False)
            schema.refresh_from_db()
        if case == "no_running_job":
            job.status = ExternalDataJob.Status.COMPLETED
            job.save()

        with patch(TASK_DELAY) as mock_delay, django_capture_on_commit_callbacks(execute=True):
            schema.should_sync = case == "re_enable"
            schema.save()

        mock_delay.assert_not_called()

    def test_queryset_update_dispatches_only_for_rows_that_were_syncing(self, team, django_capture_on_commit_callbacks):
        syncing_schema, _ = _create_schema_with_running_job(team)
        disabled_schema, _ = _create_schema_with_running_job(team)
        ExternalDataSchema.objects.filter(pk=disabled_schema.pk).update(should_sync=False)

        with patch(TASK_DELAY) as mock_delay, django_capture_on_commit_callbacks(execute=True):
            ExternalDataSchema.objects.filter(pk__in=[syncing_schema.pk, disabled_schema.pk]).update(should_sync=False)

        mock_delay.assert_called_once()
        assert mock_delay.call_args.kwargs["schema_id"] == str(syncing_schema.id)
        assert mock_delay.call_args.kwargs["reason"] == SYNC_DISABLED_JOB_ERROR

    def test_bulk_soft_delete_dispatches_with_deleted_reason(self, team, django_capture_on_commit_callbacks):
        schema, _job = _create_schema_with_running_job(team)

        with patch(TASK_DELAY) as mock_delay, django_capture_on_commit_callbacks(execute=True):
            ExternalDataSchema.objects.filter(pk=schema.pk).update(deleted=True)

        mock_delay.assert_called_once()
        assert mock_delay.call_args.kwargs["reason"] == SCHEMA_DELETED_JOB_ERROR

    def test_soft_delete_save_dispatches_with_deleted_reason(self, team, django_capture_on_commit_callbacks):
        schema, _job = _create_schema_with_running_job(team)

        with patch(TASK_DELAY) as mock_delay, django_capture_on_commit_callbacks(execute=True):
            schema.soft_delete()

        mock_delay.assert_called_once()
        assert mock_delay.call_args.kwargs["reason"] == SCHEMA_DELETED_JOB_ERROR

    def test_update_should_sync_carries_error_and_workflow_exclusion(self, team, django_capture_on_commit_callbacks):
        schema, job = _create_schema_with_running_job(team)

        with (
            patch(TASK_DELAY) as mock_delay,
            patch(
                "products.data_warehouse.backend.logic.data_load.service.external_data_workflow_exists",
                return_value=False,
            ),
            django_capture_on_commit_callbacks(execute=True),
        ):
            update_should_sync(
                schema_id=str(schema.id),
                team_id=team.pk,
                should_sync=False,
                disable_error_message="Your account does not have access to this table",
                disable_exclude_workflow_id=job.workflow_id,
            )

        mock_delay.assert_called_once_with(
            team_id=team.pk,
            schema_id=str(schema.id),
            reason="Your account does not have access to this table",
            exclude_workflow_id=job.workflow_id,
        )


class TestSweepStoppedSchemaSyncs:
    @pytest.mark.parametrize("deleted", [False, True], ids=["disabled", "deleted"])
    def test_sweep_dispatches_teardown_only_for_stopped_schemas_with_running_jobs(self, deleted, team):
        stopped_schema, _running_job = _create_schema_with_running_job(team)
        _healthy_schema, _healthy_job = _create_schema_with_running_job(team)
        idle_schema, idle_job = _create_schema_with_running_job(team)
        idle_job.status = ExternalDataJob.Status.COMPLETED
        idle_job.save()
        fresh_schema, _fresh_job = _create_schema_with_running_job(team)
        old_schema, old_job = _create_schema_with_running_job(team)

        update = {"deleted": True} if deleted else {"should_sync": False}
        ExternalDataSchema.objects.filter(
            pk__in=[stopped_schema.pk, idle_schema.pk, fresh_schema.pk, old_schema.pk]
        ).update(**update)

        # fresh_schema keeps its just-created updated_at (inside the grace window); the
        # rest are backdated past it. old_job predates the sweep's max age.
        now = timezone.now()
        ExternalDataSchema.objects.exclude(pk=fresh_schema.pk).update(
            updated_at=now - STOPPED_SYNC_SWEEP_GRACE - timedelta(minutes=1)
        )
        ExternalDataJob.objects.filter(pk=old_job.pk).update(
            created_at=now - STOPPED_SYNC_SWEEP_MAX_JOB_AGE - timedelta(days=1)
        )

        with patch(TASK_DELAY) as mock_delay:
            sweep_stopped_schema_syncs()

        mock_delay.assert_called_once_with(
            team_id=team.pk,
            schema_id=str(stopped_schema.id),
            reason=SCHEMA_DELETED_JOB_ERROR if deleted else SYNC_DISABLED_JOB_ERROR,
        )


@pytest.fixture(autouse=True)
def _keep_test_connection():
    # The reused consumer fail path calls close_old_connections(), which closes the
    # pytest-django test connection out from under the test transaction.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.close_old_connections"
    ):
        yield


@pytest.fixture
def queue_conn() -> Generator[psycopg.Connection[Any]]:
    url = _get_test_database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        _ensure_tables(conn)
        _truncate_tables(conn)
        with patch("products.warehouse_sources.backend.sync_teardown.WAREHOUSE_SOURCES_DATABASE_URL", url):
            yield conn


@pytest.fixture
def fake_redis():
    client = fakeredis.FakeRedis()

    @contextmanager
    def _fake_client():
        yield client

    with patch.object(sync_lock, "_get_redis_client", _fake_client):
        yield client


class TestCleanupTaskReenableGuard:
    @pytest.mark.parametrize("syncing_again", [True, False], ids=["reenabled_skips", "disabled_proceeds"])
    def test_stale_dispatch_leaves_a_reenabled_schema_alone(self, syncing_again, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        if not syncing_again:
            ExternalDataSchema.objects.filter(pk=schema.pk).update(should_sync=False)

        with patch("products.data_warehouse.backend.facade.api.cancel_external_data_workflow") as mock_cancel:
            cleanup_disabled_external_data_schema(
                team_id=team.pk, schema_id=str(schema.id), reason=SYNC_DISABLED_JOB_ERROR
            )

        job.refresh_from_db()
        if syncing_again:
            assert job.status == ExternalDataJob.Status.RUNNING
            mock_cancel.assert_not_called()
        else:
            assert job.status == ExternalDataJob.Status.FAILED
            mock_cancel.assert_called_once_with(job.workflow_id)


class TestTeardownSchemaSyncs:
    def test_fails_batches_finalizes_job_releases_locks_and_cancels_workflow(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)
        _insert_lease(queue_conn, team_id=team.pk, schema_id=str(schema.id), live=False)
        assert job.workflow_run_id is not None
        assert sync_lock.acquire_v3_pipeline_lock(team.pk, str(schema.id), job.workflow_run_id)

        with patch("products.data_warehouse.backend.facade.api.cancel_external_data_workflow") as mock_cancel:
            teardown_schema_syncs(team_id=team.pk, schema_id=str(schema.id), reason="stopped for test")

        assert _failed_status_counts_by_run(queue_conn) == {run_uuid: 2}
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        assert job.latest_error == "stopped for test"
        assert _lease_count(queue_conn, str(schema.id)) == 0
        assert sync_lock.get_v3_pipeline_lock_holder(team.pk, str(schema.id)) is None
        mock_cancel.assert_called_once_with(job.workflow_id)

    def test_exclude_workflow_skips_cancel_but_still_fails_batches(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)

        with patch("products.data_warehouse.backend.facade.api.cancel_external_data_workflow") as mock_cancel:
            teardown_schema_syncs(
                team_id=team.pk,
                schema_id=str(schema.id),
                reason="stopped for test",
                exclude_workflow_id=job.workflow_id,
            )

        mock_cancel.assert_not_called()
        assert _failed_status_counts_by_run(queue_conn) == {run_uuid: 2}
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED

    def test_running_job_without_queue_batches_is_finalized(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)

        with patch("products.data_warehouse.backend.facade.api.cancel_external_data_workflow") as mock_cancel:
            teardown_schema_syncs(team_id=team.pk, schema_id=str(schema.id), reason="stopped for test")

        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.FAILED
        mock_cancel.assert_called_once_with(job.workflow_id)

    def test_second_run_is_a_noop(self, team, queue_conn, fake_redis):
        _, schema, job = _create_pipeline(team)
        run_uuid = str(uuid4())
        _seed_active_run(queue_conn, team=team, schema=schema, job=job, run_uuid=run_uuid)

        with patch("products.data_warehouse.backend.facade.api.cancel_external_data_workflow") as mock_cancel:
            teardown_schema_syncs(team_id=team.pk, schema_id=str(schema.id), reason="first reason")
            second = teardown_schema_syncs(team_id=team.pk, schema_id=str(schema.id), reason="second reason")

        # No pending batches remain, the job is already terminal, and the finished
        # workflow is not re-cancelled, so the retry changes nothing.
        assert _failed_status_counts_by_run(queue_conn) == {run_uuid: 2}
        job.refresh_from_db()
        assert job.latest_error == "first reason"
        assert second.batches_failed == 0
        assert second.jobs_finalized == 0
        assert mock_cancel.call_count == 1
