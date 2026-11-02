"""The check a built suggestion passes before anyone can save it as a draft, and the save an agent's build uses."""

from typing import Any, cast
from uuid import UUID

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.event_usage import EventSource
from posthog.models import Team, User

from products.workflows.backend.facade.activity import log_workflow_activity
from products.workflows.backend.facade.contracts import WorkflowActor
from products.workflows.backend.facade.writes import create_workflow
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer

logger = structlog.get_logger(__name__)


def checked_draft(
    team: Team, workflow: dict[str, Any], event_source: EventSource, request: Request | None = None
) -> dict[str, Any]:
    """The draft as the create endpoint would store it. Raises the `ValidationError` the create endpoint would."""
    # Checked the way the caller's own create request will be: the web editor saves drafts with blank inputs, an API
    # client's draft must be complete. The graph wiring is checked in full either way.
    serializer = HogFlowSerializer(
        data={**workflow, "status": "draft"},
        context={
            "team_id": team.id,
            "get_team": lambda: team,
            "is_draft": True,
            "event_source": event_source,
            # Checks gated on the user, like cohort conditions, need the caller's request.
            "request": request,
        },
    )
    validate_graph(workflow["actions"], workflow["edges"])
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def validated_draft(team: Team, workflow: dict[str, Any], event_source: EventSource) -> dict[str, Any] | None:
    try:
        return checked_draft(team, workflow, event_source)
    except ValidationError as error:
        logger.info("workflows.data_suggestions.invalid_workflow", team_id=team.id, errors=str(error.detail)[:500])
        return None


def save_draft(team: Team, user: User, validated: dict[str, Any]) -> str:
    """Saves the draft the way the create endpoint does, activity log included, and returns its id."""
    result = create_workflow(team_id=team.id, user_id=user.id, validated_data=validated)
    workflow_id = cast(UUID, result.current["id"])
    log_workflow_activity(
        actor=WorkflowActor(organization_id=team.organization_id, team_id=team.id, user=user, was_impersonated=False),
        workflow_id=workflow_id,
        name=cast("str | None", result.current.get("name")),
        activity="created",
        detail_type="standard",
    )
    return str(workflow_id)
