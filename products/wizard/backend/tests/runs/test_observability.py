from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.test import override_settings

from kombu.exceptions import OperationalError
from prometheus_client import REGISTRY

from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
)
from products.wizard.backend.facade.enums import (
    WizardRunArtifactType,
    WizardRunEnvironment,
    WizardRunErrorCode,
    WizardRunStage,
    WizardRunStatus,
)
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM
from products.wizard.backend.logic.runs import dispatch, lifecycle
from products.wizard.backend.logic.runs.errors import WizardRunDispatchError
from products.wizard.backend.logic.workers.contracts import WizardWorkerResourceUsage, WizardWorkerTelemetry
from products.wizard.backend.observability import events, metrics, service
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome, WizardWorkerCleanupOutcome
from products.wizard.backend.observability.service import WizardObservability
from products.wizard.backend.observability.worker_usage import worker_usage_observation
from products.wizard.backend.temporal.contracts import WizardRunActivityInput
from products.wizard.backend.temporal.errors import WizardTemporalError


def _cloud_run() -> WizardRunDTO:
    created_at = datetime(2026, 8, 25, 12, tzinfo=UTC)

    return WizardRunDTO(
        id=uuid4(),
        team_id=1,
        created_by_id=2,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
        program=POSTHOG_INTEGRATION_PROGRAM,
        status=WizardRunStatus.CREATED,
        error_code=None,
        error_message=None,
        stage=WizardRunStage.DISPATCHING,
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        finished_at=None,
        deadline_at=created_at + timedelta(hours=1),
    )


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return value if value is not None else 0


@pytest.mark.django_db
def test_run_creation_emits_observability(team, user) -> None:
    with patch("products.wizard.backend.logic.runs.lifecycle.run_observability") as observability:
        run = lifecycle.create_run(
            CreateWizardRunInput(
                team_id=team.id,
                created_by_id=user.id,
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="example"),
                program_id="posthog-integration",
            )
        )

    observability.run_created.assert_called_once_with(run)


@pytest.mark.django_db
def test_run_transition_emits_observability(team, user) -> None:
    run = lifecycle.create_run(
        CreateWizardRunInput(
            team_id=team.id,
            created_by_id=user.id,
            environment=WizardRunEnvironment.LOCAL,
            workspace=LocalFolderWorkspace(project_name="example"),
            program_id="posthog-integration",
        )
    )

    with patch("products.wizard.backend.logic.runs.lifecycle.run_observability") as observability:
        completed = lifecycle.complete_run(team.id, run.id)

    observability.run_transitioned.assert_called_once_with(run, completed)


def test_stage_update_is_idempotent() -> None:
    run = replace(_cloud_run(), stage=WizardRunStage.PROVISIONING)

    with (
        patch.object(lifecycle.database_transaction, "atomic"),
        patch.object(lifecycle.store, "get_run_for_update", return_value=run),
        patch.object(lifecycle.store, "set_run_stage") as set_run_stage,
        patch.object(lifecycle.run_observability, "stage_entered") as stage_entered,
    ):
        result = lifecycle.update_run_stage(run.team_id, run.id, WizardRunStage.PROVISIONING)

    assert result == run
    set_run_stage.assert_not_called()
    stage_entered.assert_not_called()


def test_failure_is_attributed_to_previous_stage() -> None:
    previous = replace(
        _cloud_run(),
        status=WizardRunStatus.RUNNING,
        stage=WizardRunStage.EXECUTING_WIZARD,
        started_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
    )
    current = replace(
        previous,
        status=WizardRunStatus.FAILED,
        stage=None,
        error_code=WizardRunErrorCode.EXECUTION_FAILED,
        finished_at=datetime(2026, 8, 25, 12, 2, tzinfo=UTC),
    )
    observability = WizardObservability()

    with (
        patch.object(service.metrics, "report_run_finished") as report_run_finished,
        patch.object(service.events, "enqueue_run_finished") as enqueue_run_finished,
    ):
        observability.run_transitioned(previous, current)

    report_run_finished.assert_called_once_with(current, WizardRunStage.EXECUTING_WIZARD)
    assert enqueue_run_finished.call_args.args[1] == WizardRunStage.EXECUTING_WIZARD


def test_observability_failures_do_not_escape() -> None:
    run = replace(_cloud_run(), stage=None)
    observability = WizardObservability()

    with (
        patch.object(service.metrics, "report_run_created", side_effect=ValueError("metric failed")),
        patch.object(service.events, "enqueue_run_created", side_effect=OperationalError("event failed")),
    ):
        observability.run_created(run)


def test_observability_does_not_hide_programming_errors() -> None:
    run = replace(_cloud_run(), stage=None)
    observability = WizardObservability()

    with (
        patch.object(service.metrics, "report_run_created", side_effect=TypeError("bug")),
        patch.object(service.events, "enqueue_run_created"),
        pytest.raises(TypeError, match="bug"),
    ):
        observability.run_created(run)


def test_cloud_creation_records_created_and_initial_stage_metrics() -> None:
    run = _cloud_run()
    created_labels = {"environment": "cloud"}
    stage_labels = {"stage": "dispatching"}
    created_before = _sample("posthog_wizard_runs_created_total", created_labels)
    stage_before = _sample("posthog_wizard_run_stage_entered_total", stage_labels)

    with patch.object(events.celery_app, "signature"):
        WizardObservability().run_created(run)

    assert _sample("posthog_wizard_runs_created_total", created_labels) == created_before + 1
    assert _sample("posthog_wizard_run_stage_entered_total", stage_labels) == stage_before + 1


def test_dispatch_and_stage_metrics_record_funnel() -> None:
    dispatch_labels = {"outcome": WizardRunDispatchOutcome.SUCCEEDED.value}
    stage_labels = {"stage": WizardRunStage.PROVISIONING.value}
    dispatch_before = _sample("posthog_wizard_run_dispatch_attempts_total", dispatch_labels)
    stage_before = _sample("posthog_wizard_run_stage_entered_total", stage_labels)

    metrics.report_dispatch_finished(WizardRunDispatchOutcome.SUCCEEDED)
    metrics.report_stage_entered(WizardRunStage.PROVISIONING)

    assert _sample("posthog_wizard_run_dispatch_attempts_total", dispatch_labels) == dispatch_before + 1
    assert _sample("posthog_wizard_run_stage_entered_total", stage_labels) == stage_before + 1


def test_active_cloud_run_metric_tracks_status_and_stage() -> None:
    created = _cloud_run()
    running = replace(
        created,
        status=WizardRunStatus.RUNNING,
        stage=WizardRunStage.PROVISIONING,
    )
    completed = replace(running, status=WizardRunStatus.COMPLETED, stage=None)
    created_labels = {"status": "created", "stage": "dispatching"}
    provisioning_labels = {"status": "running", "stage": "provisioning"}
    created_before = _sample("posthog_wizard_cloud_runs_active", created_labels)
    provisioning_before = _sample("posthog_wizard_cloud_runs_active", provisioning_labels)

    metrics.report_run_created(created)
    metrics.report_run_status_changed(created, running)
    metrics.report_run_status_changed(running, completed)

    assert _sample("posthog_wizard_cloud_runs_active", created_labels) == created_before
    assert _sample("posthog_wizard_cloud_runs_active", provisioning_labels) == provisioning_before


def test_failure_metrics_record_stage_and_error_code() -> None:
    run = replace(
        _cloud_run(),
        status=WizardRunStatus.FAILED,
        stage=None,
        error_code=WizardRunErrorCode.EXECUTION_FAILED,
        started_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
        finished_at=datetime(2026, 8, 25, 12, 2, tzinfo=UTC),
    )
    finished_labels = {
        "environment": "cloud",
        "status": "failed",
        "error_code": "execution_failed",
    }
    failure_labels = {
        "environment": "cloud",
        "stage": "executing_wizard",
        "error_code": "execution_failed",
    }
    duration_labels = {"environment": "cloud", "status": "failed"}
    finished_before = _sample("posthog_wizard_runs_finished_total", finished_labels)
    failure_before = _sample("posthog_wizard_run_failures_total", failure_labels)
    duration_before = _sample("posthog_wizard_run_duration_seconds_sum", duration_labels)

    metrics.report_run_finished(run, WizardRunStage.EXECUTING_WIZARD)

    assert _sample("posthog_wizard_runs_finished_total", finished_labels) == finished_before + 1
    assert _sample("posthog_wizard_run_failures_total", failure_labels) == failure_before + 1
    assert _sample("posthog_wizard_run_duration_seconds_sum", duration_labels) == duration_before + 60


def test_dispatch_reports_success() -> None:
    run = _cloud_run()

    with (
        patch.object(dispatch.store, "get_run", return_value=run),
        patch.object(dispatch.temporal_client, "start_wizard_run_workflow"),
        patch.object(dispatch.store, "mark_dispatch_succeeded"),
        patch.object(dispatch.wizard_observability, "dispatch_finished") as dispatch_finished,
    ):
        dispatch.dispatch_created_cloud_wizard_run_to_temporal_worker(run.team_id, run.id)

    dispatch_finished.assert_called_once_with(run, WizardRunDispatchOutcome.SUCCEEDED)


@override_settings(DEBUG=True, LOCAL_WIZARD_ROOT="/tmp/posthog-wizard")
def test_dispatch_enables_local_wizard_source() -> None:
    run = _cloud_run()

    with (
        patch.object(dispatch.store, "get_run", return_value=run),
        patch.object(dispatch.temporal_client, "start_wizard_run_workflow") as start_workflow,
        patch.object(dispatch.store, "mark_dispatch_succeeded"),
        patch.object(dispatch.wizard_observability, "dispatch_finished"),
    ):
        dispatch.dispatch_created_cloud_wizard_run_to_temporal_worker(run.team_id, run.id)

    start_workflow.assert_called_once_with(
        WizardRunActivityInput(team_id=run.team_id, run_id=run.id, use_local_wizard_source=True)
    )


def test_dispatch_reports_failure() -> None:
    run = _cloud_run()

    with (
        patch.object(dispatch.store, "get_run", return_value=run),
        patch.object(
            dispatch.temporal_client,
            "start_wizard_run_workflow",
            side_effect=WizardTemporalError,
        ),
        patch.object(dispatch.store, "mark_dispatch_failed") as mark_dispatch_failed,
        patch.object(dispatch.wizard_observability, "dispatch_finished") as dispatch_finished,
        pytest.raises(WizardRunDispatchError),
    ):
        dispatch.dispatch_created_cloud_wizard_run_to_temporal_worker(run.team_id, run.id)

    mark_dispatch_failed.assert_called_once_with(run.team_id, run.id)
    dispatch_finished.assert_called_once_with(run, WizardRunDispatchOutcome.FAILED)


def test_worker_metrics_record_usage_and_allocated_resources() -> None:
    telemetry = WizardWorkerTelemetry(
        resource_usage=WizardWorkerResourceUsage(
            cpu_cores=2,
            memory_gb=4,
            disk_size_gb=16,
            ttl_seconds=4500,
            ttl_expires_at=datetime(2026, 8, 25, 13, 15, tzinfo=UTC),
            provider_cpu_usage_usec=120_000_000,
            provider_billed_cpu_usage_usec=180_000_000,
            provider_usage_measured_at=datetime(2026, 8, 25, 12, 30, tzinfo=UTC),
        ),
        lifetime_seconds=300,
    )
    lifetime_before = _sample("posthog_wizard_worker_lifetime_seconds_sum")
    cpu_before = _sample("posthog_wizard_worker_cpu_usage_seconds_sum")
    billed_cpu_before = _sample("posthog_wizard_worker_billed_cpu_usage_seconds_sum")
    allocated_cpu_before = _sample("posthog_wizard_worker_allocated_cpu_core_seconds_sum")
    allocated_memory_before = _sample("posthog_wizard_worker_allocated_memory_gb_seconds_sum")
    allocated_disk_before = _sample("posthog_wizard_worker_allocated_disk_gb_seconds_sum")

    metrics.report_worker_usage(worker_usage_observation(telemetry))

    assert _sample("posthog_wizard_worker_lifetime_seconds_sum") == lifetime_before + 300
    assert _sample("posthog_wizard_worker_cpu_usage_seconds_sum") == cpu_before + 120
    assert _sample("posthog_wizard_worker_billed_cpu_usage_seconds_sum") == billed_cpu_before + 180
    assert _sample("posthog_wizard_worker_allocated_cpu_core_seconds_sum") == allocated_cpu_before + 600
    assert _sample("posthog_wizard_worker_allocated_memory_gb_seconds_sum") == allocated_memory_before + 1200
    assert _sample("posthog_wizard_worker_allocated_disk_gb_seconds_sum") == allocated_disk_before + 4800


def test_worker_metrics_skip_unavailable_provider_usage() -> None:
    telemetry = WizardWorkerTelemetry(
        resource_usage=WizardWorkerResourceUsage(
            cpu_cores=2,
            memory_gb=4,
            disk_size_gb=16,
            ttl_seconds=4500,
            ttl_expires_at=datetime(2026, 8, 25, 13, 15, tzinfo=UTC),
        ),
        lifetime_seconds=300,
    )
    cpu_before = _sample("posthog_wizard_worker_cpu_usage_seconds_count")
    billed_cpu_before = _sample("posthog_wizard_worker_billed_cpu_usage_seconds_count")

    metrics.report_worker_usage(worker_usage_observation(telemetry))

    assert _sample("posthog_wizard_worker_cpu_usage_seconds_count") == cpu_before
    assert _sample("posthog_wizard_worker_billed_cpu_usage_seconds_count") == billed_cpu_before


def test_reliability_metrics_record_artifacts_cleanup_and_deadlines() -> None:
    artifact = WizardRunGitDiffArtifactDTO(
        id=uuid4(),
        team_id=1,
        run_id=uuid4(),
        artifact_type=WizardRunArtifactType.GIT_DIFF,
        size_bytes=10,
        content_hash="hash",
        additions=0,
        removals=0,
        created_at=datetime(2026, 8, 25, 12, tzinfo=UTC),
    )
    artifact_labels = {"type": "git_diff"}
    cleanup_labels = {"outcome": "succeeded"}
    deadline_labels = {"environment": "cloud"}
    artifact_before = _sample("posthog_wizard_artifacts_created_total", artifact_labels)
    cleanup_before = _sample("posthog_wizard_worker_cleanups_total", cleanup_labels)
    deadline_before = _sample("posthog_wizard_runs_past_deadline_total", deadline_labels)

    metrics.report_artifact_created(artifact)
    metrics.report_worker_cleanup(WizardWorkerCleanupOutcome.SUCCEEDED)
    metrics.report_run_past_deadline(_cloud_run())

    assert _sample("posthog_wizard_artifacts_created_total", artifact_labels) == artifact_before + 1
    assert _sample("posthog_wizard_worker_cleanups_total", cleanup_labels) == cleanup_before + 1
    assert _sample("posthog_wizard_runs_past_deadline_total", deadline_labels) == deadline_before + 1


def test_stage_event_has_deterministic_identity_and_run_properties() -> None:
    run = replace(_cloud_run(), stage=WizardRunStage.PROVISIONING)

    with patch.object(events.celery_app, "signature") as signature:
        events.enqueue_stage_entered(run, WizardRunStage.PROVISIONING)
        events.enqueue_stage_entered(run, WizardRunStage.PROVISIONING)

    first_args = signature.call_args_list[0].kwargs["args"]
    second_args = signature.call_args_list[1].kwargs["args"]

    assert first_args[4] == second_args[4]
    assert first_args[5] == {
        "environment": "cloud",
        "workspace_type": "git_repository",
        "program_id": "posthog-integration",
        "wizard_version": POSTHOG_INTEGRATION_PROGRAM.wizard_version,
        "stage": "provisioning",
    }
