from uuid import NAMESPACE_URL, uuid5

from celery import current_app as celery_app

from products.wizard.backend.facade.contracts import WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunStage
from products.wizard.backend.observability.config import (
    WIZARD_ANALYTICS_TASK,
    WIZARD_PULL_REQUEST_CREATED_EVENT,
    WIZARD_RUN_CREATED_EVENT,
    WIZARD_RUN_DISPATCH_FINISHED_EVENT,
    WIZARD_RUN_STAGE_ENTERED_EVENT,
    WIZARD_WORKER_USAGE_RECORDED_EVENT,
)
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome, WizardWorkerUsageObservation

type WizardEventProperty = str | int | float | bool | None
type WizardEventProperties = dict[str, WizardEventProperty]


def enqueue_run_created(run: WizardRunDTO) -> None:
    _enqueue_run_event(run, WIZARD_RUN_CREATED_EVENT, "created")


def enqueue_dispatch_finished(run: WizardRunDTO, outcome: WizardRunDispatchOutcome) -> None:
    _enqueue_run_event(
        run,
        WIZARD_RUN_DISPATCH_FINISHED_EVENT,
        f"dispatch:{outcome.value}",
        {"outcome": outcome.value},
    )


def enqueue_stage_entered(run: WizardRunDTO, stage: WizardRunStage) -> None:
    _enqueue_run_event(
        run,
        WIZARD_RUN_STAGE_ENTERED_EVENT,
        f"stage:{stage.value}",
        {"stage": stage.value},
    )


def enqueue_run_finished(run: WizardRunDTO, failure_stage: WizardRunStage | None, event: str) -> None:
    properties: WizardEventProperties = {
        "status": run.status.value,
        "error_code": run.error_code,
        "failure_stage": failure_stage.value if failure_stage is not None else None,
    }

    if run.started_at is not None and run.finished_at is not None:
        properties["duration_seconds"] = max((run.finished_at - run.started_at).total_seconds(), 0)

    _enqueue_run_event(run, event, f"terminal:{run.status.value}", properties)


def enqueue_worker_usage(run: WizardRunDTO, usage: WizardWorkerUsageObservation) -> None:
    _enqueue_run_event(
        run,
        WIZARD_WORKER_USAGE_RECORDED_EVENT,
        "worker_usage",
        {
            "lifetime_seconds": usage.lifetime_seconds,
            "cpu_cores": usage.cpu_cores,
            "memory_gb": usage.memory_gb,
            "disk_size_gb": usage.disk_size_gb,
            "cpu_usage_seconds": usage.cpu_usage_seconds,
            "billed_cpu_usage_seconds": usage.billed_cpu_usage_seconds,
        },
    )


def enqueue_pull_request_created(run: WizardRunDTO) -> None:
    _enqueue_run_event(run, WIZARD_PULL_REQUEST_CREATED_EVENT, "artifact:pull_request")


def _enqueue_run_event(
    run: WizardRunDTO,
    event: str,
    event_key: str,
    properties: WizardEventProperties | None = None,
) -> None:
    event_uuid = uuid5(NAMESPACE_URL, f"wizard:{run.id}:{event_key}")
    event_properties: WizardEventProperties = {
        "environment": run.environment.value,
        "workspace_type": run.workspace.type,
        "program_id": run.program.id,
        "wizard_version": run.program.wizard_version,
    }

    if properties is not None:
        event_properties.update(properties)

    celery_app.signature(
        WIZARD_ANALYTICS_TASK,
        args=[run.team_id, run.created_by_id, str(run.id), event, str(event_uuid), event_properties],
    ).apply_async()
