from datetime import timedelta

from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.mcp_analytics.backend.facade.contracts import WrappedSnapshot
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped
from products.mcp_analytics.backend.wrapped.cards import SCHEMA_VERSION

# A wrap is a moment, not a report. It shows for this long after the job fills it, then the pop-up and the
# header button go away on their own until someone runs the job again.
DISPLAY_WINDOW = timedelta(days=14)

# The event properties the wrap's cards are computed from (see queries.py). The job runs without a user, so the
# stored cards can't be redacted per member: a member who may not read any of these gets no wrap at all.
WRAPPED_SOURCE_PROPERTIES = frozenset(
    {
        "$mcp_tool_name",
        "$mcp_exec_target_tool",
        "$mcp_exec_verb",
        "$mcp_exec_tool_call_name",
        "$mcp_client_name",
        "$mcp_client_user_agent",
        "$mcp_vendor_client",
        "mcp_vendor_client",
        "$mcp_llm_model",
        "$mcp_server_name",
        "$mcp_is_error",
        "$mcp_duration_ms",
    }
)


def get_fresh_wrapped(team: Team, user: User | None) -> WrappedSnapshot | None:
    # The job saves a project's wrap under its parent team, which a child environment reads too. Restrictions are
    # set per environment, so the parent's rules apply to that read as well as the child's own.
    data_team_id = team.parent_team_id or team.pk
    for team_id in {team.pk, data_team_id}:
        restricted = split_restricted_property_names(
            get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
        ).event
        if WRAPPED_SOURCE_PROPERTIES & restricted:
            return None
    with team_scope(team.id):
        snapshot = (
            MCPAnalyticsWrapped.objects.filter(
                team_id=data_team_id,
                status=MCPAnalyticsWrapped.Status.READY,
                schema_version=SCHEMA_VERSION,
                generated_at__gte=timezone.now() - DISPLAY_WINDOW,
            )
            .order_by("-generated_at")
            .first()
        )
    if snapshot is None:
        return None
    return WrappedSnapshot(
        year=snapshot.year,
        generated_at=snapshot.generated_at,
        expires_at=snapshot.generated_at + DISPLAY_WINDOW,
        cards=snapshot.payload,
    )
