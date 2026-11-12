from uuid import NAMESPACE_URL, uuid5

from posthog.models import User
from posthog.ph_client import ScopedCapture, ph_background_capture

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardPullRequestState, WizardRunEnvironment, WizardRunStage
from products.wizard.backend.observability.config import (
    WIZARD_RUN_ARTIFACT_CREATED_EVENT,
    WIZARD_RUN_DISPATCH_FINISHED_EVENT,
    WIZARD_RUN_FINISHED_EVENT,
    WIZARD_RUN_PULL_REQUEST_CLOSED_EVENT,
    WIZARD_RUN_PULL_REQUEST_MERGED_EVENT,
    WIZARD_RUN_STAGE_ENTERED_EVENT,
    WIZARD_RUN_STARTED_EVENT,
    WIZARD_WORKER_USAGE_RECORDED_EVENT,
)
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome, WizardWorkerUsageObservation

type WizardEventProperty = str | int | float | bool | None
type WizardEventProperties = dict[str, WizardEventProperty]


def enqueue_run_created(run: WizardRunDTO) -> None:
    _enqueue_run_event(
        run,
        WIZARD_RUN_STARTED_EVENT,
        "started",
        {
            "location": "wizard_library",
            "program": run.program.name,
        },
    )


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


def enqueue_run_finished(run: WizardRunDTO, failure_stage: WizardRunStage | None) -> None:
    properties: WizardEventProperties = {
        "status": run.status.value,
        "error_code": run.error_code,
        "failure_stage": failure_stage.value if failure_stage is not None else None,
    }

    if run.started_at is not None and run.finished_at is not None:
        properties["duration_seconds"] = max((run.finished_at - run.started_at).total_seconds(), 0)

    _enqueue_run_event(run, WIZARD_RUN_FINISHED_EVENT, f"terminal:{run.status.value}", properties)


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


def enqueue_artifact_created(run: WizardRunDTO, artifact: WizardRunArtifactDTO) -> None:
    if isinstance(artifact, WizardRunPullRequestArtifactDTO):
        properties: WizardEventProperties = {
            "type": "pull_request",
            "url": artifact.url,
            "name": f"Pull request #{artifact.number}",
        }
    elif isinstance(artifact, WizardRunGitDiffArtifactDTO):
        properties = {"type": "diff", "url": None, "name": "Git diff"}

    _enqueue_run_event(run, WIZARD_RUN_ARTIFACT_CREATED_EVENT, f"artifact:{artifact.id}", properties)


def enqueue_pull_request_finished(
    run: WizardRunDTO, artifact: WizardRunPullRequestArtifactDTO, capture: ScopedCapture
) -> None:
    merged = artifact.state == WizardPullRequestState.MERGED
    _enqueue_run_event(
        run,
        WIZARD_RUN_PULL_REQUEST_MERGED_EVENT if merged else WIZARD_RUN_PULL_REQUEST_CLOSED_EVENT,
        f"pull_request:{artifact.id}:{'merged' if merged else 'closed'}",
        {
            "artifact_id": str(artifact.id),
            "url": artifact.url,
            "pr_number": artifact.number,
            "merged_at": artifact.merged_at.isoformat() if artifact.merged_at else None,
            "closed_at": artifact.closed_at.isoformat() if artifact.closed_at else None,
        },
        capture,
    )


def _enqueue_run_event(
    run: WizardRunDTO,
    event: str,
    event_key: str,
    properties: WizardEventProperties | None = None,
    capture: ScopedCapture | None = None,
) -> None:
    event_uuid = uuid5(NAMESPACE_URL, f"wizard:{run.id}:{event_key}")
    event_properties: WizardEventProperties = {
        "event_source": "wizard_run_service",
        "project_id": str(run.team_id),
        "environment": run.environment.value,
        "run_surface": run.environment.value,
        "workspace_type": run.workspace.type,
        "program_id": run.program.id,
        "wizard_version": run.program.wizard_version,
        "version": run.program.wizard_version,
        "command": run.program.command[0] if run.program.command else "default",
    }

    if run.environment == WizardRunEnvironment.CLOUD:
        event_properties["task_run_id"] = str(run.id)

    if properties is not None:
        event_properties.update(properties)

    distinct_id = str(run.id)
    if run.created_by_id is not None:
        user_distinct_id = User.objects.filter(id=run.created_by_id).values_list("distinct_id", flat=True).first()
        if user_distinct_id is not None:
            distinct_id = user_distinct_id
    (capture or ph_background_capture())(
        distinct_id=distinct_id,
        event=event,
        properties={**event_properties, "team_id": run.team_id, "wizard_run_id": str(run.id)},
        uuid=str(event_uuid),
    )
