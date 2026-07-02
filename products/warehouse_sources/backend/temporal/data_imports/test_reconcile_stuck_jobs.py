import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import Organization, Team

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.metrics import LOCK_TAKEOVER_LATEST_ERROR
from products.warehouse_sources.backend.temporal.data_imports.reconcile_stuck_jobs import (
    find_stuck_running_jobs,
    reclaim_job_if_workflow_terminal,
    reconcile_stuck_running_jobs,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.reconcile_stuck_jobs"

# Any non-RUNNING WorkflowExecutionStatus is terminal; the enum value is irrelevant to the
# decision, so a sentinel object standing in for "terminal" keeps these tests import-light.
TERMINAL = MagicMock(name="COMPLETED")


def _make_job(**overrides: Any) -> MagicMock:
    job = MagicMock()
    job.id = overrides.get("id", uuid.uuid4())
    job.team_id = overrides.get("team_id", 1)
    job.schema_id = overrides.get("schema_id", uuid.uuid4())
    job.workflow_id = overrides.get("workflow_id", "external-data-job-abc")
    job.workflow_run_id = overrides.get("workflow_run_id", "run-abc-123")
    return job


class TestReclaimJobIfWorkflowTerminal:
    def _run(self, *, describe_return: Any, queue_return: Any, job: MagicMock | None = None):
        job = job or _make_job()
        with (
            patch(f"{MODULE}._describe_workflow_status", return_value=describe_return),
            patch(f"{MODULE}._run_queue_is_reclaimable", return_value=queue_return),
            patch(f"{MODULE}.update_external_job_status") as mock_update,
            patch(f"{MODULE}.release_v3_pipeline_lock") as mock_release,
        ):
            outcome = reclaim_job_if_workflow_terminal(job, MagicMock())
        return outcome, mock_update, mock_release

    @patch(f"{MODULE}._describe_workflow_status")
    def test_running_workflow_is_left_alone(self, mock_describe: MagicMock) -> None:
        from temporalio.client import WorkflowExecutionStatus

        mock_describe.return_value = WorkflowExecutionStatus.RUNNING
        with (
            patch(f"{MODULE}.update_external_job_status") as mock_update,
            patch(f"{MODULE}.release_v3_pipeline_lock") as mock_release,
        ):
            outcome = reclaim_job_if_workflow_terminal(_make_job(), MagicMock())

        assert outcome == "workflow_running"
        mock_update.assert_not_called()
        mock_release.assert_not_called()

    def test_describe_error_fails_closed(self) -> None:
        outcome, mock_update, mock_release = self._run(describe_return=None, queue_return=True)
        assert outcome == "describe_error"
        mock_update.assert_not_called()
        mock_release.assert_not_called()

    def test_queue_error_fails_closed(self) -> None:
        outcome, mock_update, mock_release = self._run(describe_return=TERMINAL, queue_return=None)
        assert outcome == "queue_error"
        mock_update.assert_not_called()
        mock_release.assert_not_called()

    def test_active_consumer_is_not_stolen(self) -> None:
        outcome, mock_update, mock_release = self._run(describe_return=TERMINAL, queue_return=False)
        assert outcome == "active_consumer"
        mock_update.assert_not_called()
        mock_release.assert_not_called()

    def test_terminal_workflow_with_reclaimable_run_is_failed_and_lock_released(self) -> None:
        job = _make_job()
        outcome, mock_update, mock_release = self._run(describe_return=TERMINAL, queue_return=True, job=job)

        assert outcome == "reclaimed"
        assert mock_update.call_args.kwargs["job_id"] == str(job.id)
        assert mock_update.call_args.kwargs["status"] == ExternalDataJob.Status.FAILED
        assert mock_update.call_args.kwargs["latest_error"] == LOCK_TAKEOVER_LATEST_ERROR
        mock_release.assert_called_once_with(job.team_id, str(job.schema_id), job.workflow_run_id)

    @pytest.mark.parametrize(
        "overrides",
        [{"workflow_id": None}, {"workflow_run_id": None}, {"schema_id": None}],
        ids=["no_workflow_id", "no_run_id", "no_schema"],
    )
    def test_unverifiable_job_is_never_failed(self, overrides: dict[str, Any]) -> None:
        # Without a workflow to describe or a schema to update we cannot prove the job is dead,
        # so it must be left for the opportunistic takeover rather than force-failed.
        outcome, mock_update, mock_release = self._run(
            describe_return=TERMINAL, queue_return=True, job=_make_job(**overrides)
        )
        assert outcome == "unverifiable"
        mock_update.assert_not_called()
        mock_release.assert_not_called()

    def test_fail_error_does_not_release_lock(self) -> None:
        job = _make_job()
        with (
            patch(f"{MODULE}._describe_workflow_status", return_value=TERMINAL),
            patch(f"{MODULE}._run_queue_is_reclaimable", return_value=True),
            patch(f"{MODULE}.update_external_job_status", side_effect=Exception("db down")),
            patch(f"{MODULE}.release_v3_pipeline_lock") as mock_release,
        ):
            outcome = reclaim_job_if_workflow_terminal(job, MagicMock())

        assert outcome == "fail_error"
        mock_release.assert_not_called()

    def test_lock_release_failure_still_counts_as_reclaimed(self) -> None:
        # The job is already failed; a lingering lock only delays the next sync until its TTL.
        job = _make_job()
        with (
            patch(f"{MODULE}._describe_workflow_status", return_value=TERMINAL),
            patch(f"{MODULE}._run_queue_is_reclaimable", return_value=True),
            patch(f"{MODULE}.update_external_job_status"),
            patch(f"{MODULE}.release_v3_pipeline_lock", side_effect=Exception("redis down")),
        ):
            outcome = reclaim_job_if_workflow_terminal(job, MagicMock())

        assert outcome == "reclaimed"


class TestReconcileStuckRunningJobs:
    def test_one_job_erroring_does_not_abort_the_sweep(self) -> None:
        jobs = [_make_job(), _make_job(), _make_job()]
        with (
            patch(f"{MODULE}.find_stuck_running_jobs", return_value=jobs),
            patch(f"{MODULE}.sync_connect", return_value=MagicMock()),
            patch(
                f"{MODULE}.reclaim_job_if_workflow_terminal",
                side_effect=["reclaimed", Exception("boom"), "workflow_running"],
            ) as mock_reclaim,
        ):
            outcomes = reconcile_stuck_running_jobs()

        assert mock_reclaim.call_count == 3
        assert outcomes == {"reclaimed": 1, "error": 1, "workflow_running": 1}

    def test_no_candidates_skips_temporal_connect(self) -> None:
        with (
            patch(f"{MODULE}.find_stuck_running_jobs", return_value=[]),
            patch(f"{MODULE}.sync_connect") as mock_connect,
        ):
            outcomes = reconcile_stuck_running_jobs()

        assert outcomes == {}
        mock_connect.assert_not_called()


@pytest.mark.django_db
class TestFindStuckRunningJobs:
    def _team(self) -> Team:
        org = Organization.objects.create(name="Org")
        return Team.objects.create(organization=org, name="Team")

    def _source(self, team: Team) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status="running",
            source_type="Stripe",
        )

    def _job(self, team, source, *, status, pipeline_version, age_seconds: int) -> ExternalDataJob:
        job = ExternalDataJob.objects.create(
            team=team, pipeline=source, status=status, pipeline_version=pipeline_version
        )
        # updated_at is auto_now, so bypass it with a raw UPDATE to control staleness.
        ExternalDataJob.objects.filter(id=job.id).update(updated_at=timezone.now() - dt.timedelta(seconds=age_seconds))
        return job

    def test_selects_only_stale_running_v3_jobs(self) -> None:
        team = self._team()
        source = self._source(team)
        V3 = ExternalDataJob.PipelineVersion.V3
        RUNNING = ExternalDataJob.Status.RUNNING

        stale_v3 = self._job(team, source, status=RUNNING, pipeline_version=V3, age_seconds=7200)
        self._job(team, source, status=RUNNING, pipeline_version=V3, age_seconds=60)  # too fresh
        self._job(team, source, status=ExternalDataJob.Status.COMPLETED, pipeline_version=V3, age_seconds=7200)
        self._job(team, source, status=RUNNING, pipeline_version=ExternalDataJob.PipelineVersion.V2, age_seconds=7200)

        found = find_stuck_running_jobs(min_age_seconds=3600, limit=50)

        assert [j.id for j in found] == [stale_v3.id]

    def test_orders_oldest_first_and_respects_limit(self) -> None:
        team = self._team()
        source = self._source(team)
        V3 = ExternalDataJob.PipelineVersion.V3
        RUNNING = ExternalDataJob.Status.RUNNING

        oldest = self._job(team, source, status=RUNNING, pipeline_version=V3, age_seconds=10800)
        middle = self._job(team, source, status=RUNNING, pipeline_version=V3, age_seconds=7200)
        self._job(team, source, status=RUNNING, pipeline_version=V3, age_seconds=5400)

        found = find_stuck_running_jobs(min_age_seconds=3600, limit=2)

        assert [j.id for j in found] == [oldest.id, middle.id]
