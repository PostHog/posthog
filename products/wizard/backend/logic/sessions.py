"""
Business logic for Wizard sessions.
"""

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardSessionDTO, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.logic.utils import is_stale
from products.wizard.backend.models import WizardSession


def upsert_session(params: UpsertWizardSessionInput) -> WizardSessionDTO:
    instance, _ = WizardSession.objects.update_or_create(
        team_id=params.team_id,
        session_id=params.session_id,
        defaults={
            "workflow_id": params.workflow_id,
            "skill_id": params.skill_id,
            "started_at": params.started_at,
            "run_phase": params.run_phase.value,
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                }
                for task in params.tasks
            ],
            "event_plan": params.event_plan,
            "error": params.error,
        },
    )
    return _to_dto(instance)


def get_session(team_id: int, session_id: str) -> WizardSessionDTO | None:
    instance = WizardSession.objects.filter(team_id=team_id, session_id=session_id).first()
    return _to_dto(instance) if instance else None


def get_latest_session(team_id: int, workflow_id: str, skill_id: str) -> WizardSessionDTO | None:
    instance = (
        WizardSession.objects.filter(team_id=team_id, workflow_id=workflow_id, skill_id=skill_id)
        .order_by("-started_at")
        .first()
    )
    return _to_dto(instance) if instance else None


def list_sessions(
    team_id: int,
    workflow_id: str | None = None,
    skill_id: str | None = None,
) -> list[WizardSessionDTO]:
    qs = WizardSession.objects.filter(team_id=team_id)
    if workflow_id:
        qs = qs.filter(workflow_id=workflow_id)
    if skill_id:
        qs = qs.filter(skill_id=skill_id)
    return [_to_dto(instance) for instance in qs.order_by("-started_at")]


def _to_dto(instance: WizardSession) -> WizardSessionDTO:
    run_phase = RunPhase(instance.run_phase)
    return WizardSessionDTO(
        session_id=instance.session_id,
        team_id=instance.team_id,
        workflow_id=instance.workflow_id,
        skill_id=instance.skill_id,
        started_at=instance.started_at,
        run_phase=run_phase,
        is_stale=is_stale(run_phase, instance.updated_at),
        tasks=tuple(
            WizardTaskDTO(
                id=task["id"],
                title=task["title"],
                status=TaskStatus(task["status"]),
            )
            for task in (instance.tasks or [])
        ),
        event_plan=instance.event_plan,
        error=instance.error,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )
