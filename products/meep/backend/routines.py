from uuid import UUID, uuid5

from django.db import transaction

from rest_framework.exceptions import NotFound, PermissionDenied

from posthog.models import Team, User

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
