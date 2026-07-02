import uuid

import pytest
from unittest.mock import MagicMock, patch

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
        lock_acquired: bool,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_acquire.return_value = lock_acquired

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is lock_acquired
        assert result.token == WORKFLOW_RUN_ID
        mock_acquire.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)
        if lock_acquired:
            mock_take_over.assert_not_called()
        else:
            mock_take_over.assert_called_once()

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

    @patch(f"{MODULE}._describe_holder_workflow", return_value=(WorkflowExecutionStatus.RUNNING, None))
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_fails_closed_when_holder_workflow_running(
        self, _holder: MagicMock, _close: MagicMock, _describe: MagicMock
    ) -> None:
        assert self._run() is False

    @patch(f"{MODULE}._describe_holder_workflow", return_value=(None, None))
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_fails_closed_when_describe_fails(
        self, _holder: MagicMock, _close: MagicMock, _describe: MagicMock
    ) -> None:
        assert self._run() is False

    @patch(f"{MODULE}.acquire_v3_pipeline_lock", return_value=True)
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}._describe_holder_workflow", return_value=(WorkflowExecutionStatus.COMPLETED, None))
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_takes_over_when_no_job_row(
        self,
        _holder: MagicMock,
        _close: MagicMock,
        _describe: MagicMock,
        mock_release: MagicMock,
        mock_acquire: MagicMock,
    ) -> None:
        assert self._run() is True
        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), self.HOLDER_TOKEN)

    @pytest.mark.parametrize(
        "holder_status",
        ["Completed", "Failed"],
        ids=["holder_completed", "holder_failed"],
    )
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
        holder_status: str,
    ) -> None:
        holder_job = MagicMock()
        holder_job.status = holder_status
        with patch(
            f"{MODULE}._describe_holder_workflow",
            return_value=(WorkflowExecutionStatus.COMPLETED, holder_job),
        ):
            assert self._run() is True
        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), self.HOLDER_TOKEN)

    @patch(f"{MODULE}._take_over_stale_running_job", return_value=False)
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.get_v3_pipeline_lock_holder", return_value=HOLDER_TOKEN)
    def test_delegates_to_queue_db_when_job_running(
        self,
        _holder: MagicMock,
        _close: MagicMock,
        mock_stale: MagicMock,
    ) -> None:
        holder_job = MagicMock()
        holder_job.status = "Running"
        with patch(
            f"{MODULE}._describe_holder_workflow",
            return_value=(WorkflowExecutionStatus.COMPLETED, holder_job),
        ):
            assert self._run() is False
        mock_stale.assert_called_once()


class TestTakeOverStaleRunningJob:
    HOLDER_TOKEN = "stale-run-999"

    def _run(self) -> bool:
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
            _take_over_stale_running_job,
        )

        inputs = AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID)
        holder_job = MagicMock()
        holder_job.id = "job-123"
        holder_job.status = "Running"
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
