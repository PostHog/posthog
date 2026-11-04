"""The project files guard for transactional email templates, which send through a workflow."""

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from rest_framework.exceptions import PermissionDenied

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
    """Deleting or restoring a transactional template needs editor access to its workflow.

    The template's own access rules don't cover the workflow it sends through, which can carry its own.
    """
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
