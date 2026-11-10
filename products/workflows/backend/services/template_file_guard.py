from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from django.db import OperationalError, transaction
from django.db.models import Model

from rest_framework.exceptions import PermissionDenied

from posthog.exceptions import Conflict

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.services.hog_flow_reads import get_workflow_ref

if TYPE_CHECKING:
    from posthog.api.file_system.deletion import DeletionContext, RestoreContext
    from posthog.models import Team


class LinkedTemplate(Protocol):
    team_id: int
    team: "Team"
    transactional_hog_flow_id: UUID | None


def require_linked_workflow_editor(context: "DeletionContext | RestoreContext", template: LinkedTemplate) -> None:
    if template.transactional_hog_flow_id is None:
        return
    denied = "You need editor access to this template's transactional email workflow."
    if context.user is None:
        raise PermissionDenied(denied)
    try:
        get_workflow_ref(
            team_id=template.team_id,
            workflow_id=str(template.transactional_hog_flow_id),
            user_access_control=UserAccessControl(user=context.user, team=template.team),
            required_level="editor",
        )
    except WorkflowAccessDenied:
        raise PermissionDenied(denied) from None
    except WorkflowNotFound:
        return


def lock_template_for_delete(template: Model) -> None:
    try:
        with transaction.atomic():
            list(type(template)._base_manager.select_for_update(nowait=True).filter(pk=template.pk).values_list("pk"))
    except OperationalError:
        raise Conflict("This template is being saved. Try again in a moment.", code="template_busy")
