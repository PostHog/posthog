from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.db import DatabaseError

from products.tasks.backend.facade.sandbox import SandboxCleanupError
from products.wizard.backend.logic.runs.errors import WizardWorkerCleanupError
from products.wizard.backend.logic.workers import lifecycle as worker_lifecycle
from products.wizard.backend.observability.contracts import WizardWorkerCleanupOutcome


def test_cleanup_worker_destroys_sandbox_when_usage_measurement_has_programming_error() -> None:
    run_id = uuid4()

    with (
        patch.object(worker_lifecycle.worker_store, "mark_cleanup_pending"),
        patch.object(worker_lifecycle.cloud_worker, "measure_worker_usage", side_effect=RuntimeError("bug")),
        patch.object(worker_lifecycle.cloud_worker, "destroy_worker") as destroy_worker,
        patch.object(worker_lifecycle.worker_store, "mark_cleaned"),
    ):
        with pytest.raises(RuntimeError, match="bug"):
            worker_lifecycle.cleanup_worker(1, run_id, "sandbox-id")

    destroy_worker.assert_called_once_with("sandbox-id")


def test_cleanup_worker_destroys_sandbox_when_usage_persistence_fails() -> None:
    run_id = uuid4()
    usage = MagicMock()

    with (
        patch.object(worker_lifecycle.worker_store, "mark_cleanup_pending"),
        patch.object(worker_lifecycle.cloud_worker, "measure_worker_usage", return_value=usage),
        patch.object(worker_lifecycle.worker_store, "record_usage", side_effect=DatabaseError),
        patch.object(worker_lifecycle.cloud_worker, "destroy_worker") as destroy_worker,
        patch.object(worker_lifecycle.worker_store, "mark_cleaned") as mark_cleaned,
        patch.object(worker_lifecycle, "_report_worker_usage"),
        patch.object(worker_lifecycle.wizard_observability, "worker_cleanup_finished") as cleanup_finished,
    ):
        worker_lifecycle.cleanup_worker(1, run_id, "sandbox-id")

    destroy_worker.assert_called_once_with("sandbox-id")
    mark_cleaned.assert_called_once_with(1, run_id)
    cleanup_finished.assert_called_once_with(1, run_id, WizardWorkerCleanupOutcome.SUCCEEDED)


def test_cleanup_worker_translates_sandbox_cleanup_failure() -> None:
    run_id = uuid4()
    cleanup_error = SandboxCleanupError("cleanup failed", {}, RuntimeError("provider unavailable"), capture=False)

    with (
        patch.object(worker_lifecycle.worker_store, "mark_cleanup_pending"),
        patch.object(worker_lifecycle.cloud_worker, "measure_worker_usage", return_value=None),
        patch.object(worker_lifecycle.cloud_worker, "destroy_worker", side_effect=cleanup_error),
        patch.object(worker_lifecycle.worker_store, "mark_cleanup_failed") as mark_cleanup_failed,
        patch.object(worker_lifecycle.wizard_observability, "worker_cleanup_finished") as cleanup_finished,
    ):
        with pytest.raises(WizardWorkerCleanupError):
            worker_lifecycle.cleanup_worker(1, run_id, "sandbox-id")

    mark_cleanup_failed.assert_called_once_with(1, run_id)
    cleanup_finished.assert_called_once_with(1, run_id, WizardWorkerCleanupOutcome.FAILED)


def test_cleanup_worker_reports_persisted_usage_after_cleanup() -> None:
    run_id = uuid4()
    run = MagicMock()
    telemetry = MagicMock()

    with (
        patch.object(worker_lifecycle.worker_store, "mark_cleanup_pending"),
        patch.object(worker_lifecycle.cloud_worker, "measure_worker_usage", return_value=None),
        patch.object(worker_lifecycle.cloud_worker, "destroy_worker"),
        patch.object(worker_lifecycle.worker_store, "mark_cleaned"),
        patch.object(worker_lifecycle.run_store, "get_run", return_value=run),
        patch.object(worker_lifecycle.worker_store, "get_worker_telemetry", return_value=telemetry),
        patch.object(worker_lifecycle.wizard_observability, "worker_usage_recorded") as worker_usage_recorded,
    ):
        worker_lifecycle.cleanup_worker(1, run_id, "sandbox-id")

    worker_usage_recorded.assert_called_once_with(run, telemetry)
