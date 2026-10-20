"""Workflow ideas prepared ahead of time by `prepare_workflow_ideas`, each stored with its built workflow.

A project with waiting premade ideas sees only those cards, read from Postgres. No generation run starts for it.
"""

import copy
import hashlib
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import BuiltSuggestion, DataSuggestion, WorkflowIdeaAlreadyResolved
from products.workflows.backend.facade.enums import WorkflowIdeaStatus
from products.workflows.backend.models import HogFlow, WorkflowIdea
from products.workflows.backend.services.data_suggestions.builder import EmailSender


def premade_suggestions(team: Team) -> tuple[DataSuggestion, ...]:
    # A stored workflow can be large, and the cards only need the metadata.
    rows = _waiting(team.id).defer("definition").order_by("created_at")
    return tuple(premade_card(row) for row in rows)


def waiting_premade_count(team_id: int) -> int:
    return _waiting(team_id).count()


def is_premade_idea(team_id: int, idea_id: str) -> bool:
    return _is_uuid(idea_id) and _premade(team_id).filter(id=idea_id).exists()


def store_premade_ideas(*, team: Team, built: Sequence[tuple[DataSuggestion, BuiltSuggestion]]) -> tuple[str, ...]:
    """Stores each built suggestion as a waiting idea and returns the stored titles. A key the project already
    accepted or dismissed is not offered again."""
    stored: list[str] = []
    with transaction.atomic():
        for suggestion, build in built:
            if build.workflow is None:
                continue
            _, created = WorkflowIdea.objects.for_team(team.id).get_or_create(
                team_id=team.id,
                # Event names can be longer than the key column.
                key="event:" + hashlib.sha256(suggestion.trigger_event.encode()).hexdigest()[:32],
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
                    },
                },
            )
            if created:
                stored.append(suggestion.name)
    return tuple(stored)


def lock_premade_idea(team_id: int, idea_id: str) -> WorkflowIdea | None:
    """The waiting premade idea, locked until the transaction ends, or None when the id is not a premade idea."""
    if not _is_uuid(idea_id):
        return None
    row = _premade(team_id).select_for_update().filter(id=idea_id).first()
    if row is not None and row.status != WorkflowIdeaStatus.SUGGESTED:
        raise WorkflowIdeaAlreadyResolved()
    return row


def waiting_premade_idea(team_id: int, idea_id: str) -> WorkflowIdea | None:
    if not _is_uuid(idea_id):
        return None
    return _waiting(team_id).filter(id=idea_id).first()


def mark_accepted(row: WorkflowIdea, *, team_id: int, hog_flow_id: str, user: User) -> None:
    row.status = WorkflowIdeaStatus.ACCEPTED
    # The draft is not committed yet, so a replica read would not find it.
    row.hog_flow = HogFlow.objects.using("default").get(team_id=team_id, id=hog_flow_id)
    row.resolved_at = timezone.now()
    row.resolved_by = user
    row.save(update_fields=["status", "hog_flow", "resolved_at", "resolved_by"])


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


def with_sender(workflow: dict[str, Any], sender: EmailSender | None) -> dict[str, Any]:
    """Fills each blank email sender, because the project may have verified one after the idea was built."""
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


def _premade(team_id: int) -> QuerySet[WorkflowIdea]:
    # for_team() also matches the parent project's ideas from a child environment, which an environment-scoped key
    # must not read.
    return WorkflowIdea.objects.for_team(team_id).filter(team_id=team_id).exclude(definition={})


def _waiting(team_id: int) -> QuerySet[WorkflowIdea]:
    return _premade(team_id).filter(status=WorkflowIdeaStatus.SUGGESTED)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
