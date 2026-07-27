import uuid
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import WorkflowExecutionStatus

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    RunActivitySummary,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    CheckPipelineVersionActivityInputs,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)

TEAM_ID = 1
SCHEMA_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
WORKFLOW_RUN_ID = "run-abc-123"

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock"


def _uuid7_token(age_seconds: float) -> str:
    ms = int((datetime.now(UTC) - timedelta(seconds=age_seconds)).timestamp() * 1000)
    return str(uuid.UUID(int=(ms << 80) | (0x7 << 76) | (0x2 << 62)))


class TestCheckPipelineVersionActivity:
    @pytest.mark.parametrize(
        "ff_enabled, expected_is_v3",
        [
            (False, False),
            (True, True),
        ],
        ids=["v2", "v3"],
    )
    @patch(f"{MODULE}.is_pipeline_v3_enabled")
    @patch(f"{MODULE}.ExternalDataSource")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.bind_contextvars")
    def test_returns_ff_result(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
        mock_v3_check: MagicMock,
        ff_enabled: bool,
        expected_is_v3: bool,
    ) -> None:
        mock_source = MagicMock()
        mock_source.source_type = "Stripe"
        mock_source_model.objects.get.return_value = mock_source
        mock_v3_check.return_value = ff_enabled

        result = check_pipeline_version_activity(
            CheckPipelineVersionActivityInputs(team_id=TEAM_ID, source_id=SOURCE_ID)
        )

        assert result.is_v3 is expected_is_v3
        mock_v3_check.assert_called_once_with(TEAM_ID, "Stripe")

    @patch(f"{MODULE}.ExternalDataSource")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.bind_contextvars")
    def test_source_not_found_returns_not_v3(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
    ) -> None:
        mock_source_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_source_model.objects.get.side_effect = mock_source_model.DoesNotExist

        result = check_pipeline_version_activity(
            CheckPipelineVersionActivityInputs(team_id=TEAM_ID, source_id=SOURCE_ID)
        )

        assert result.is_v3 is False


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
    @patch(f"{MODULE}._describe_holder_workflow", return_value=(WorkflowExecutionStatus.RUNNING, None, False))
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_fails_closed_when_holder_workflow_running(
        self, _holder: MagicMock, _close: MagicMock, _describe: MagicMock, _meta: MagicMock
    ) -> None:
        assert self._run() is False

    @patch(f"{MODULE}.get_v3_pipeline_lock_meta", return_value=None)
    @patch(f"{MODULE}._describe_holder_workflow", return_value=(None, None, False))
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
            return_value=(WorkflowExecutionStatus.COMPLETED, holder_job, False),
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
            return_value=(WorkflowExecutionStatus.COMPLETED, holder_job, False),
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

    @patch(f"{MODULE}._release_and_acquire", return_value=True)
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_takes_over_when_stale_batches(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_release: MagicMock,
    ) -> None:
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=True
        )
        assert self._run() is True
        mock_update.assert_called_once()

    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_fails_closed_when_active_consumer(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
    ) -> None:
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=False
        )
        assert self._run() is False

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_fails_closed_when_queue_db_unreachable(
        self,
        mock_conn_cls: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        mock_conn_cls.connect.side_effect = RuntimeError("connection refused")
        assert self._run() is False

    @freeze_time("2026-01-01T12:00:00Z")
    @patch(f"{MODULE}._release_and_acquire", return_value=True)
    @patch(f"{MODULE}.update_external_job_status")
    @patch(f"{MODULE}.BatchQueue")
    @patch(f"{MODULE}.psycopg.Connection")
    def test_max_hold_exceeded_takes_over_despite_active_consumer(
        self,
        mock_conn_cls: MagicMock,
        mock_queue: MagicMock,
        mock_update: MagicMock,
        mock_release: MagicMock,
    ) -> None:
        # Without the max-hold backstop, a fooled staleness heuristic can block
        # takeover forever.
        mock_queue.get_run_activity_summary.return_value = RunActivitySummary(
            has_batches=True, has_non_terminal=True, is_stale=False
        )
        assert self._run(holder_created_at=datetime.now(UTC) - timedelta(hours=25)) is True
        mock_update.assert_called_once()

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
