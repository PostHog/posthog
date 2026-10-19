"""Workflow ideas prepared ahead of time by `prepare_workflow_ideas`, each stored with its built workflow.

A project with waiting premade ideas sees only those cards, read from Postgres. No generation run starts for it.
"""

import copy
import hashlib
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import (
    BuiltSuggestion,
    DataSuggestion,
    WorkflowIdeaAlreadyResolved,
    WorkflowIdeaNotFound,
    WorkflowIdeaWorkflowMismatch,
)
from products.workflows.backend.facade.enums import WorkflowIdeaStatus
from products.workflows.backend.models import HogFlow, WorkflowIdea
from products.workflows.backend.services.data_suggestions import team_context
from products.workflows.backend.services.data_suggestions.builder import EmailSender

_KEY_PREFIX = "event:"


def _waiting(team_id: int):
    return WorkflowIdea.objects.for_team(team_id).filter(status=WorkflowIdeaStatus.SUGGESTED).exclude(definition={})


def premade_suggestions(team: Team) -> tuple[DataSuggestion, ...]:
    # A stored workflow can be large, and the cards only need the metadata.
    rows = _waiting(team.id).defer("definition").order_by("created_at")
    return tuple(premade_card(row) for row in rows)


def waiting_premade_count(team_id: int) -> int:
    return _waiting(team_id).count()


def premade_build(team: Team, idea_id: str) -> BuiltSuggestion | None:
    """The idea's stored workflow, ready to save as a draft, or None when the id is not a waiting premade idea."""
    row = _waiting_row(team.id, idea_id)
    if row is None:
        return None
    # The project may have verified a sender after the idea was built.
    workflow = _with_sender(row.definition, team_context.email_sender(team))
    return BuiltSuggestion(
        status="ready",
        workflow=workflow,
        uses_saved_template=bool(row.evidence.get("uses_saved_template")),
    )


def store_premade_ideas(
    *, team: Team, built: Sequence[tuple[DataSuggestion, BuiltSuggestion]], replace: bool, source_ref: str
) -> tuple[str, ...]:
    """Stores each built suggestion as a waiting idea and returns the stored titles. With `replace`, the ideas still
    waiting are removed first, unless nothing new was built. A key the project already accepted or dismissed is not
    offered again."""
    stored: list[str] = []
    with transaction.atomic():
        if replace and built:
            _waiting(team.id).delete()
        for suggestion, build in built:
            if build.workflow is None:
                continue
            _, created = WorkflowIdea.objects.for_team(team.id).get_or_create(
                team_id=team.id,
                key=_idea_key(suggestion.trigger_event),
                defaults={
                    "title": suggestion.name,
                    "rationale": suggestion.reason,
                    "definition": build.workflow,
                    "evidence": {
                        "description": suggestion.description,
                        "trigger_event": suggestion.trigger_event,
                        "weekly_count": suggestion.weekly_count,
                        "stage": suggestion.stage,
                        "step_outline": list(suggestion.step_outline),
                        "uses_saved_template": build.uses_saved_template,
                        "measured_at": timezone.now().isoformat(),
                    },
                    "source_ref": source_ref,
                },
            )
            if created:
                stored.append(suggestion.name)
    return tuple(stored)


def accept_premade_idea(
    *, team: Team, idea_id: str, hog_flow_id: str, user: User, access: UserAccessControl | None
) -> None:
    """Links the draft a person created from the idea, so the idea stops being offered. Without `access` the caller
    has just saved the draft itself."""
    with transaction.atomic():
        row = lock_premade_idea(team.id, idea_id)
        # Locked so two ideas accepted at once cannot both claim the same draft.
        hog_flow = (
            HogFlow.objects.select_for_update()
            .filter(team_id=team.id, id=hog_flow_id, status=HogFlow.State.DRAFT)
            .first()
        )
        if (
            hog_flow is None
            or (access is not None and not access.check_access_level_for_object(hog_flow, required_level="editor"))
            or WorkflowIdea.objects.for_team(team.id).filter(hog_flow=hog_flow).exists()
        ):
            raise WorkflowIdeaWorkflowMismatch()
        row.status = WorkflowIdeaStatus.ACCEPTED
        row.hog_flow = hog_flow
        row.resolved_at = timezone.now()
        row.resolved_by = user
        row.save(update_fields=["status", "hog_flow", "resolved_at", "resolved_by"])


def lock_premade_idea(team_id: int, idea_id: str) -> WorkflowIdea:
    if not _is_uuid(idea_id):
        raise WorkflowIdeaNotFound()
    row = WorkflowIdea.objects.for_team(team_id).select_for_update().filter(id=idea_id).first()
    if row is None:
        raise WorkflowIdeaNotFound()
    if row.status != WorkflowIdeaStatus.SUGGESTED:
        raise WorkflowIdeaAlreadyResolved()
    return row


def _waiting_row(team_id: int, idea_id: str) -> WorkflowIdea | None:
    if not _is_uuid(idea_id):
        return None
    return _waiting(team_id).filter(id=idea_id).first()


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _idea_key(trigger_event: str) -> str:
    # Event names can be longer than the key column.
    return _KEY_PREFIX + hashlib.sha256(trigger_event.encode()).hexdigest()[:32]


def premade_card(row: WorkflowIdea) -> DataSuggestion:
    evidence = row.evidence or {}
    return DataSuggestion(
        id=str(row.id),
        name=row.title,
        description=str(evidence.get("description") or row.rationale),
        reason=row.rationale,
        trigger_event=str(evidence.get("trigger_event") or ""),
        weekly_count=int(evidence.get("weekly_count") or 0),
        stage=evidence.get("stage") or "other",
        step_outline=tuple(evidence.get("step_outline") or ()),
        premade=True,
    )


def _with_sender(workflow: dict[str, Any], sender: EmailSender | None) -> dict[str, Any]:
    if sender is None:
        return workflow
    filled = copy.deepcopy(workflow)
    for action in filled.get("actions") or []:
        if action.get("type") != "function_email":
            continue
        email = cast(dict[str, Any], ((action.get("config") or {}).get("inputs") or {}).get("email") or {})
        value = email.get("value")
        if isinstance(value, dict) and not (value.get("from") or {}).get("email"):
            value["from"] = {"integrationId": sender.integration_id, "email": sender.email, "name": sender.name}
    return filled
