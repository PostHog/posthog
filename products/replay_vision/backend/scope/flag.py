"""Whether a team writes scopes yet.

The refactor lands behind this flag so the API can accept a `scope` and refuse the experiment
scanner type for one team at a time, while every other team keeps today's behavior.
"""

import posthoganalytics

from posthog.models.team import Team
from posthog.models.user import User

SCOPE_FLAG = "vision-scanner-scope"


def scope_api_enabled(team: Team, user: "User | None") -> bool:
    """True when this caller may write a `scope` and must stop using the experiment scanner type.

    Evaluated per organization, because a scanner's editor, its MCP tools and the AI drafter all
    have to agree on which shape a team writes; splitting that by user would let two people in one
    team write scanners the other's editor cannot represent.

    An anonymous caller reads as off. Evaluating the flag needs a distinct id, and the paths that
    reach here without a user are service tokens, which must keep today's behavior.
    """
    if user is None or not user.is_authenticated:
        return False
    organization_id = str(team.organization_id)
    return bool(
        posthoganalytics.feature_enabled(
            SCOPE_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
        )
    )
