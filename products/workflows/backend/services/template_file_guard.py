from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID
from weakref import WeakKeyDictionary

from django.db import OperationalError, transaction
from django.db.models import Model

from psycopg.errors import LockNotAvailable
from rest_framework.exceptions import PermissionDenied

from posthog.exceptions import Conflict

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from posthog.api.file_system.deletion import DeletionContext, FileChangeContext, RestoreContext
    from posthog.models import Team, User


class LinkedTemplate(Protocol):
    team_id: int
    team: "Team"
    transactional_hog_flow_id: UUID | None


# A folder delete runs this guard once per template while it holds row locks. So each request keeps one
# UserAccessControl per user and team, because an instance loads the team's access rules once and caches
# them. It also keeps the access fields of the linked workflows, which the prepare hook reads in one query
# before the first lock. The weak keys drop both caches with the request.
_ACCESS_FIELDS = ("id", "team_id", "created_by_id")
_access_controls_by_request: "WeakKeyDictionary[Any, dict[tuple[Any, int], UserAccessControl]]" = WeakKeyDictionary()
_workflows_by_request: "WeakKeyDictionary[Any, dict[tuple[int, str], HogFlow | None]]" = WeakKeyDictionary()


def _access_control_for(request: Any | None, user: "User", template: LinkedTemplate) -> UserAccessControl:
    if request is None:
        return UserAccessControl(user=user, team=template.team)
    access_controls = _access_controls_by_request.setdefault(request, {})
    key = (user.pk, template.team_id)
    if key not in access_controls:
        access_controls[key] = UserAccessControl(user=user, team=template.team)
    return access_controls[key]


def prepare_linked_workflows(request: Any | None, team_id: int, templates: "QuerySet[Any]") -> None:
    if request is None:
        return
    workflows = _workflows_by_request.setdefault(request, {})
    linked_ids = [
        linked_id
        for linked_id in templates.filter(transactional_hog_flow_id__isnull=False).values_list(
            "transactional_hog_flow_id", flat=True
        )
        if (team_id, str(linked_id)) not in workflows
    ]
    if not linked_ids:
        return
    workflows.update({(team_id, str(linked_id)): None for linked_id in linked_ids})
    for flow in HogFlow.objects.filter(team_id=team_id, pk__in=linked_ids).only(*_ACCESS_FIELDS):
        workflows[(flow.team_id, str(flow.id))] = flow


def _linked_workflow(request: Any | None, template: LinkedTemplate) -> HogFlow | None:
    key = (template.team_id, str(template.transactional_hog_flow_id))
    if request is not None and key in _workflows_by_request.get(request, {}):
        return _workflows_by_request[request][key]
    return HogFlow.objects.filter(team_id=key[0], pk=key[1]).only(*_ACCESS_FIELDS).first()


def require_linked_workflow_editor(
    context: "DeletionContext | RestoreContext | FileChangeContext", template: LinkedTemplate
) -> None:
    if template.transactional_hog_flow_id is None:
        return
    denied = "You need editor access to this template's transactional email workflow."
    user = context.user
    if user is None:
        raise PermissionDenied(denied)
    workflow = _linked_workflow(context.request, template)
    if workflow is None:
        return
    access_control = _access_control_for(context.request, user, template)
    if not access_control.check_access_level_for_object(workflow, required_level="editor"):
        raise PermissionDenied(denied)


def lock_templates_for_delete(templates: "QuerySet[Any]") -> list[Model]:
    try:
        with transaction.atomic():
            return list(templates.select_for_update(nowait=True))
    except OperationalError as error:
        if not isinstance(error.__cause__, LockNotAvailable):
            raise
        raise Conflict("This template is being saved. Try again in a moment.", code="template_busy")
