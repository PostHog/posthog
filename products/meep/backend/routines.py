from datetime import UTC, datetime
from uuid import UUID, uuid5

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from posthog.models import Team, User

from products.meep.backend.facade.contracts import RoutineDetails, RoutineStep
from products.meep.backend.models import Topic
from products.meep.backend.replication import apply_command
from products.meep.backend.scouts import bound_topic
from products.workflows.backend.facade import api as workflows


@transaction.atomic
def bind_topic_routine(
    *, team: Team, user: User, task_id: UUID, topic_id: UUID, workflow_id: UUID, name: str, trigger: str
) -> dict[str, str]:
    canonical_team = team.parent_team or team
    if not workflows.can_edit_workflows(team_id=canonical_team.pk, user_id=user.pk):
        raise PermissionDenied("Linking a routine requires workflow editor access.")
    topic = bound_topic(team, user, task_id, topic_id)
    if not workflows.workflow_exists(team_id=canonical_team.pk, workflow_id=workflow_id):
        raise NotFound("Workflow not found in this project.")
    routine = {
        "id": f"workflow-{workflow_id}",
        "name": name,
        "trigger": trigger,
        "backend": "posthog",
        "external_id": str(workflow_id),
        "watches": [],
    }
    # A retry finds the receipt of the first call, so one workflow binds once.
    apply_command(
        topic.team_id,
        user,
        uuid5(topic.pk, f"routine:{workflow_id}"),
        topic.pk,
        {"kind": "SetRoutine", "routine": routine},
    )
    return {"id": routine["id"], "name": name, "trigger": trigger, "workflow_id": str(workflow_id)}


def routine_details(*, team_id: int, owner_id: int, topic_id: UUID, routine: str) -> RoutineDetails:
    topic = get_object_or_404(
        Topic.objects.for_team(team_id), owner_id=owner_id, pk=topic_id, archived=False, deleted=False
    )
    binding = next(
        (
            r
            for r in (topic.state or {}).get("topic", {}).get("routines", [])
            if r["id"] == routine and r["backend"] == "posthog"
        ),
        None,
    )
    if binding is None:
        raise NotFound("Routine not found in this topic.")
    try:
        summary = workflows.get_workflow_summary(team_id=team_id, workflow_id=binding["external_id"])
    except workflows.WorkflowNotFound:
        raise NotFound("Workflow not found in this project.")
    graph = [
        RoutineStep(id=a.id, kind=a.kind, name=a.name, detail=a.description)
        for a in workflows.get_workflow_actions(team_id=team_id, workflow_id=binding["external_id"])
    ]
    return RoutineDetails(
        enabled=summary.status == "active",
        name=summary.name or binding["name"],
        trigger=binding["trigger"],
        steps=[step.name for step in graph],
        graph=graph,
    )


@transaction.atomic
def add_topic_context(
    *,
    team: Team,
    user: User,
    task_id: UUID,
    topic_id: UUID,
    kind: str,
    text: str,
    current: float | None,
    target: float | None,
    unit: str,
    effect: str,
    action: str,
) -> dict[str, str]:
    topic = bound_topic(team, user, task_id, topic_id)
    key = uuid5(topic.pk, f"context:{kind}:{text}:{effect}:{action}")
    now = datetime.now(UTC).isoformat()
    if kind == "goal":
        progress = (
            {"Target": {"current": current, "target": target, "unit": unit}}
            if current is not None and target is not None
            else None
        )
        command = {"kind": "AddGoal", "goal": {"id": str(key), "text": text, "progress": progress}}
    elif kind == "fact":
        command = {
            "kind": "AddFact",
            "fact": {
                "id": str(key),
                "text": text,
                "provenance": {"author": "Topic agent", "via": "topic chat", "at": now, "thread": None},
                "superseded_by": None,
            },
        }
    elif kind == "rule":
        command = {
            "kind": "AddRule",
            "rule": {
                "id": str(key),
                "text": text,
                "effect": {effect.capitalize(): action},
                "from_task": None,
                "created_at": now,
            },
        }
    else:
        raise ValidationError("Choose goal, fact or rule.")
    apply_command(topic.team_id, user, key, topic.pk, command)
    return {"kind": kind, "id": str(key), "text": text}
