import uuid
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

import psycopg
from temporalio.client import WorkflowExecutionStatus

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    CheckPipelineVersionActivityInputs,
    HolderWorkflowDescription,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)
from products.warehouse_sources_queue.backend.core.jobs_db import RunActivitySummary
from products.warehouse_sources_queue.backend.sdk import JobLiveness

TEAM_ID = 1
SCHEMA_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
WORKFLOW_RUN_ID = "run-abc-123"

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock"


def _uuid7_token(age_seconds: float) -> str:
    ms = int((datetime.now(UTC) - timedelta(seconds=age_seconds)).timestamp() * 1000)
    return str(uuid.UUID(int=(ms << 80) | (0x7 << 76) | (0x2 << 62)))


class TestCheckPipelineVersionActivity:
    # Pre-patch workflow histories still schedule this activity. It must answer V3 without a
    # database read, so a replayed run never asks for the removed V2 pipeline.
    @pytest.mark.parametrize("schema_id", [None, SCHEMA_ID], ids=["legacy_payload", "with_schema"])
    def test_always_returns_v3(self, schema_id: uuid.UUID | None) -> None:
        result = check_pipeline_version_activity(
            CheckPipelineVersionActivityInputs(team_id=TEAM_ID, source_id=SOURCE_ID, schema_id=schema_id)
        )

        assert result.is_v3 is True


class TestAcquireV3PipelineLockActivity:
    @pytest.mark.parametrize(
        "lock_acquired",
        [True, False],
        ids=["lock_free", "lock_held"],
    )
    @patch(f"{MODULE}.write_v3_pipeline_lock_meta")
    @patch(f"{MODULE}._take_over_lock_if_holder_finished", return_value=False)
    @patch(f"{MODULE}.acquire_v3_pipeline_lock")
    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_lock_result(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
        mock_acquire: MagicMock,
        mock_take_over: MagicMock,
        mock_write_meta: MagicMock,
        lock_acquired: bool,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_activity.info.return_value.workflow_id = "wf-abc-123"
        mock_acquire.return_value = lock_acquired

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is lock_acquired
        assert result.token == WORKFLOW_RUN_ID
        mock_acquire.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)
        if lock_acquired:
            mock_take_over.assert_not_called()
            # Without meta, a later contender can't describe this workflow pre-job-row
            # and the takeover race guard degrades to the age grace.
            mock_write_meta.assert_called_once_with(
                TEAM_ID, str(SCHEMA_ID), run_id=WORKFLOW_RUN_ID, workflow_id="wf-abc-123"
            )
        else:
            mock_take_over.assert_called_once()
            mock_write_meta.assert_not_called()

    @patch(f"{MODULE}.write_v3_pipeline_lock_meta")
    @patch(f"{MODULE}._take_over_lock_if_holder_finished", return_value=True)
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=False)
    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_take_over_result_wins_when_holder_finished(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
        _mock_acquire: MagicMock,
        _mock_take_over: MagicMock,
        _mock_write_meta: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is True

    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_empty_workflow_run_id_fails_closed(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = ""

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is False
        assert result.token == ""


def _schema_with_config(sync_type_config: dict) -> ExternalDataSchema:
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org, name="t")
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    return ExternalDataSchema.objects.create(name="Charge", team=team, source=source, sync_type_config=sync_type_config)


def _streak(runs: int, failed_ago: timedelta) -> dict:
    return {"runs": runs, "last_failed_at": (datetime.now(UTC) - failed_ago).isoformat()}


@pytest.mark.django_db
class TestAcquireV3PipelineLockActivityDeferral:
    @pytest.mark.parametrize(
        "_name,config_extra,runs,failed_ago,expect_deferred",
        [
            ("streak_at_threshold_inside_gap", {}, 5, timedelta(minutes=2), True),
            ("long_streak_inside_capped_gap", {}, 30, timedelta(minutes=40), True),
            ("streak_at_threshold_past_gap", {}, 5, timedelta(minutes=11), False),
            ("long_streak_past_capped_gap", {}, 30, timedelta(minutes=61), False),
            ("streak_below_threshold", {}, 4, timedelta(seconds=1), False),
            ("reset_pipeline_runs_anyway", {"reset_pipeline": True}, 8, timedelta(minutes=1), False),
        ],
    )
    @patch(f"{MODULE}.write_v3_pipeline_lock_meta")
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_deferral(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
        mock_acquire: MagicMock,
        _mock_write_meta: MagicMock,
        _name: str,
        config_extra: dict,
        runs: int,
        failed_ago: timedelta,
        expect_deferred: bool,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_activity.info.return_value.workflow_id = "wf-abc-123"
        schema = _schema_with_config({**config_extra, "failure_streak": _streak(runs, failed_ago)})

        result = acquire_v3_pipeline_lock_activity(
            AcquireV3LockActivityInputs(team_id=schema.team_id, schema_id=schema.id)
        )

        assert result.deferred is expect_deferred
        assert result.acquired is not expect_deferred
        assert result.token == WORKFLOW_RUN_ID
        if expect_deferred:
            mock_acquire.assert_not_called()
        else:
            mock_acquire.assert_called_once()

    @patch(f"{MODULE}.write_v3_pipeline_lock_meta")
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.ExternalDataSchema.objects")
    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_a_failing_schema_read_does_not_stop_the_sync(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
        mock_objects: MagicMock,
        mock_acquire: MagicMock,
        _mock_write_meta: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_activity.info.return_value.workflow_id = "wf-abc-123"
        mock_objects.filter.side_effect = OperationalError("db unavailable")

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.deferred is False
        assert result.acquired is True
        mock_acquire.assert_called_once()


class TestTakeOverStaleLock:
    HOLDER_TOKEN = "stale-run-999"

    def _run(self) -> bool:
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
            _take_over_lock_if_holder_finished,
        )

        inputs = AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID)
        return _take_over_lock_if_holder_finished(inputs, WORKFLOW_RUN_ID, MagicMock())

    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=None)
    def test_retries_acquire_when_lock_vanished(self, _holder: MagicMock, mock_acquire: MagicMock) -> None:
        assert self._run() is True
        mock_acquire.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)

    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(
        f"{MODULE}._describe_holder_workflow",
        return_value=HolderWorkflowDescription(
            status=WorkflowExecutionStatus.RUNNING, job=None, status_is_assumed=False
        ),
    )
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_fails_closed_when_holder_workflow_running(
        self, _holder: MagicMock, _close: MagicMock, _describe: MagicMock, _meta: MagicMock
    ) -> None:
        assert self._run() is False

    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(
        f"{MODULE}._describe_holder_workflow",
        return_value=HolderWorkflowDescription(status=None, job=None, status_is_assumed=False),
    )
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_fails_closed_when_describe_fails(
        self, _holder: MagicMock, _close: MagicMock, _describe: MagicMock, _meta: MagicMock
    ) -> None:
        assert self._run() is False

    @pytest.mark.parametrize(
        "holder_status, expected_takeover",
        [
            (WorkflowExecutionStatus.RUNNING, False),
            (WorkflowExecutionStatus.COMPLETED, True),
            (WorkflowExecutionStatus.TERMINATED, True),
        ],
        ids=["running_fails_closed", "completed_takes_over", "terminated_takes_over"],
    )
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.sync_connect")
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.get_v3_pipeline_lock_meta")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder")
    def test_no_job_row_with_meta_asks_temporal(
        self,
        mock_holder: MagicMock,
        _close: MagicMock,
        mock_meta: MagicMock,
        mock_job_model: MagicMock,
        mock_sync_connect: MagicMock,
        mock_release: MagicMock,
        mock_acquire: MagicMock,
        holder_status: WorkflowExecutionStatus,
        expected_takeover: bool,
    ) -> None:
        # Core race: meta lets us ask Temporal instead of assuming a pre-job-row
        # holder crashed; a young token proves Temporal's answer beats the age grace.
        holder_token = _uuid7_token(age_seconds=2)
        mock_holder.return_value = holder_token
        mock_meta.return_value = {"run_id": holder_token, "workflow_id": "wf-holder-1"}
        mock_job_model.objects.filter.return_value.order_by.return_value.only.return_value.first.return_value = None
        handle = MagicMock()
        handle.describe = AsyncMock(return_value=MagicMock(status=holder_status))
        mock_sync_connect.return_value.get_workflow_handle.return_value = handle

        assert self._run() is expected_takeover
        mock_sync_connect.return_value.get_workflow_handle.assert_called_once_with("wf-holder-1", run_id=holder_token)
        if expected_takeover:
            mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), holder_token)
        else:
            mock_release.assert_not_called()

    @pytest.mark.parametrize(
        "holder_age_seconds, meta, expected_takeover",
        [
            (60, None, False),
            (7200, None, True),
            (60, {"run_id": "some-other-run", "workflow_id": "wf-stale"}, False),
            (None, None, True),
        ],
        ids=[
            "young_holder_fails_closed",
            "old_holder_takes_over",
            "stale_meta_ignored_grace_applies",
            "undecodable_token_takes_over",
        ],
    )
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.sync_connect")
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.get_v3_pipeline_lock_meta")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder")
    def test_no_job_row_without_meta_applies_age_grace(
        self,
        mock_holder: MagicMock,
        _close: MagicMock,
        mock_meta: MagicMock,
        mock_job_model: MagicMock,
        mock_sync_connect: MagicMock,
        mock_release: MagicMock,
        mock_acquire: MagicMock,
        holder_age_seconds: float | None,
        meta: dict | None,
        expected_takeover: bool,
    ) -> None:
        # Legacy/crash path (no usable meta): without a workflow_id the token's
        # UUIDv7 age decides; undecodable tokens keep today's take-over behavior.
        holder_token = _uuid7_token(holder_age_seconds) if holder_age_seconds is not None else self.HOLDER_TOKEN
        mock_holder.return_value = holder_token
        mock_meta.return_value = meta
        mock_job_model.objects.filter.return_value.order_by.return_value.only.return_value.first.return_value = None

        assert self._run() is expected_takeover
        mock_sync_connect.assert_not_called()
        if expected_takeover:
            mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), holder_token)
        else:
            mock_release.assert_not_called()

    @pytest.mark.parametrize(
        "holder_status",
        ["Completed", "Failed"],
        ids=["holder_completed", "holder_failed"],
    )
    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_takes_over_when_holder_job_terminal(
        self,
        _holder: MagicMock,
        _close: MagicMock,
        mock_release: MagicMock,
        mock_acquire: MagicMock,
        _meta: MagicMock,
        holder_status: str,
    ) -> None:
        holder_job = MagicMock()
        holder_job.status = holder_status
        with patch(
            f"{MODULE}._describe_holder_workflow",
            return_value=HolderWorkflowDescription(
                status=WorkflowExecutionStatus.COMPLETED, job=holder_job, status_is_assumed=False
            ),
        ):
            assert self._run() is True
        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), self.HOLDER_TOKEN)

    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(f"{MODULE}._take_over_stale_running_job", return_value=False)
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_delegates_to_queue_db_when_job_running(
        self,
        _holder: MagicMock,
        _close: MagicMock,
        mock_stale: MagicMock,
        _meta: MagicMock,
    ) -> None:
        holder_job = MagicMock()
        holder_job.status = "Running"
        with patch(
            f"{MODULE}._describe_holder_workflow",
            return_value=HolderWorkflowDescription(
                status=WorkflowExecutionStatus.COMPLETED, job=holder_job, status_is_assumed=False
            ),
        ):
            assert self._run() is False
        mock_stale.assert_called_once()


class TestTakeOverStaleRunningJob:
    HOLDER_TOKEN = "stale-run-999"

    def _run(self, *, holder_created_at: datetime | None = None) -> bool:
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
            _take_over_stale_running_job,
        )

        inputs = AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID)
        holder_job = MagicMock()
        holder_job.id = "job-123"
        holder_job.status = "Running"
        holder_job.created_at = holder_created_at or datetime.now(UTC) - timedelta(hours=1)
        return _take_over_stale_running_job(inputs, self.HOLDER_TOKEN, WORKFLOW_RUN_ID, holder_job, MagicMock())

    @patch(f"{MODULE}._release_and_acquire", return_value=True)
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_takes_over_when_no_batches(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_release: MagicMock,
    ) -> None:
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=False, has_non_terminal=False, is_stale=True
        )
        assert self._run() is True
        mock_update.assert_called_once()

    # A live loader keeps the lock past the max hold: a takeover lets the new run's batch 0
    # overwrite the table while the old loader is still merging and then publishing it.
    @pytest.mark.parametrize(
        "is_stale,hold_hours,expect_takeover",
        [
            pytest.param(False, 1, False, id="live_holder_within_max_hold"),
            pytest.param(False, 25, False, id="live_holder_past_max_hold"),
            pytest.param(True, 1, True, id="stale_holder_within_max_hold"),
            pytest.param(True, 25, True, id="stale_holder_past_max_hold"),
        ],
    )
    @time_machine.travel("2026-01-15 12:00:00+00:00", tick=False)
    @patch(f"{MODULE}._release_and_acquire", return_value=True)
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_takes_over_only_a_stale_holder_with_pending_batches(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_release: MagicMock,
        is_stale: bool,
        hold_hours: int,
        expect_takeover: bool,
    ) -> None:
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=is_stale
        )

        assert self._run(holder_created_at=datetime.now(UTC) - timedelta(hours=hold_hours)) is expect_takeover

        assert mock_queue.fail_batches_for_job_sync.called is expect_takeover
        assert mock_update.called is expect_takeover
        assert mock_release.called is expect_takeover

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_fails_closed_when_queue_db_unreachable(
        self,
        mock_conn_cls: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        mock_conn_cls.connect.side_effect = RuntimeError("connection refused")
        assert self._run() is False

    @patch(f"{MODULE}._release_and_acquire", return_value=True)
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_takeover_fails_the_holders_queue_batches(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_release: MagicMock,
    ) -> None:
        # Leftover claimable batches loaded after takeover stale-overwrite newer
        # data or flip the FAILED job back to COMPLETED.
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=True
        )
        assert self._run() is True
        mock_queue.fail_batches_for_job_sync.assert_called_once()
        assert mock_queue.fail_batches_for_job_sync.call_args[1]["job_id"] == "job-123"

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_fails_closed_when_queue_batch_fail_fails(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        # If the batches can't be made terminal, stealing the lock would leave
        # them claimable under a FAILED job — the exact window this guards.
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=True
        )
        mock_queue.fail_batches_for_job_sync.side_effect = RuntimeError("queue write failed")
        assert self._run() is False
        mock_update.assert_not_called()


class TestReleaseV3PipelineLockActivity:
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.bind_contextvars")
    def test_delegates_to_sync_lock(self, _bind: MagicMock, mock_release: MagicMock) -> None:
        inputs = ReleaseV3LockActivityInputs(
            team_id=TEAM_ID,
            schema_id=SCHEMA_ID,
            token=WORKFLOW_RUN_ID,
        )

        release_v3_pipeline_lock_activity(inputs)

        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)


QUEUE_HOLDER = str(uuid.uuid4())
LOOKUP_FAILED = object()


class TestTakeOverFromQueueHolder:
    @pytest.mark.parametrize(
        "meta_runner,liveness,job_status,expected,expected_path",
        [
            pytest.param(
                "queue",
                JobLiveness(latest_state="executing", is_live=True),
                None,
                False,
                None,
                id="live_queue_holder_keeps_it",
            ),
            pytest.param(
                "queue",
                JobLiveness(latest_state="waiting_retry", is_live=True),
                None,
                False,
                None,
                id="retrying_queue_holder_keeps_it",
            ),
            pytest.param("queue", None, None, True, "release", id="gone_queue_job_without_row_is_taken_over"),
            pytest.param(
                "queue",
                JobLiveness(latest_state="failed", is_live=False),
                "Failed",
                True,
                "release",
                id="failed_queue_job_terminal_row",
            ),
            pytest.param(
                "queue",
                JobLiveness(latest_state="succeeded", is_live=False),
                "Running",
                "stale_check",
                "stale_check",
                id="handed_to_loader_asks_the_loader_queue",
            ),
            pytest.param(
                None,
                JobLiveness(latest_state="succeeded", is_live=False),
                "Completed",
                True,
                "release",
                id="queue_job_found_without_meta",
            ),
            pytest.param(None, None, None, False, "temporal", id="unknown_random_uuid_goes_to_temporal"),
            pytest.param("queue", LOOKUP_FAILED, None, False, None, id="queue_lookup_error_fails_closed"),
        ],
    )
    @patch(f"{MODULE}._describe_holder_workflow")
    @patch(f"{MODULE}._take_over_stale_running_job", return_value="stale_check")
    @patch(f"{MODULE}._queue_job_liveness")
    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.get_v3_pipeline_lock_meta")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=QUEUE_HOLDER)
    def test_queue_holder(
        self,
        _holder: MagicMock,
        _close: MagicMock,
        mock_meta: MagicMock,
        mock_job_model: MagicMock,
        mock_release: MagicMock,
        _acquire: MagicMock,
        mock_liveness: MagicMock,
        mock_stale_check: MagicMock,
        mock_describe: MagicMock,
        meta_runner: str | None,
        liveness: object,
        job_status: str | None,
        expected: object,
        expected_path: str | None,
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
            take_over_v3_lock_if_holder_finished,
        )

        mock_meta.return_value = (
            {"run_id": QUEUE_HOLDER, "workflow_id": "wf", "runner": meta_runner} if meta_runner else None
        )
        if liveness is LOOKUP_FAILED:
            mock_liveness.side_effect = psycopg.OperationalError("queue db down")
        else:
            mock_liveness.return_value = liveness
        holder_job = None if job_status is None else MagicMock(status=job_status)
        mock_job_model.objects.filter.return_value.order_by.return_value.only.return_value.first.return_value = (
            holder_job
        )
        mock_describe.return_value = HolderWorkflowDescription(
            status=WorkflowExecutionStatus.RUNNING, job=None, status_is_assumed=False
        )

        assert take_over_v3_lock_if_holder_finished(TEAM_ID, SCHEMA_ID, WORKFLOW_RUN_ID, MagicMock()) == expected

        assert mock_release.called is (expected_path == "release")
        assert mock_stale_check.called is (expected_path == "stale_check")
        assert mock_describe.called is (expected_path == "temporal")

    @patch(f"{MODULE}._describe_holder_workflow")
    @patch(f"{MODULE}._queue_job_liveness")
    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder")
    def test_temporal_run_ids_skip_the_queue_lookup(
        self,
        mock_holder: MagicMock,
        _close: MagicMock,
        _meta: MagicMock,
        mock_liveness: MagicMock,
        mock_describe: MagicMock,
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
            take_over_v3_lock_if_holder_finished,
        )

        mock_holder.return_value = _uuid7_token(age_seconds=5)
        mock_describe.return_value = HolderWorkflowDescription(
            status=WorkflowExecutionStatus.RUNNING, job=None, status_is_assumed=False
        )

        assert take_over_v3_lock_if_holder_finished(TEAM_ID, SCHEMA_ID, WORKFLOW_RUN_ID, MagicMock()) is False
        mock_liveness.assert_not_called()
