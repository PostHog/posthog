"""The check a built suggestion passes before anyone can save it as a draft."""

from typing import Any

import structlog
from rest_framework.exceptions import ValidationError

from posthog.event_usage import EventSource
from posthog.models import Team

from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer

logger = structlog.get_logger(__name__)


def is_valid_draft(team: Team, workflow: dict[str, Any], event_source: EventSource) -> bool:
    # Checked the way the caller's own create request will be: the web editor saves drafts with blank inputs, an API
    # client's draft must be complete. The graph wiring is checked in full either way.
    serializer = HogFlowSerializer(
        data={**workflow, "status": "draft"},
        context={"team_id": team.id, "get_team": lambda: team, "is_draft": True, "event_source": event_source},
    )
    try:
        validate_graph(workflow["actions"], workflow["edges"])
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        logger.info("workflows.data_suggestions.invalid_workflow", team_id=team.id, errors=str(error.detail)[:500])
        return False
    return True
