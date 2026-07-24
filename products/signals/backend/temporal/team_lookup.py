from collections.abc import Sequence

import temporalio.exceptions

from posthog.models import Team

TEAM_DELETED_ERROR_TYPE = "SignalsTeamDeleted"


async def get_team_or_terminal(
    team_id: int,
    *,
    select_related: Sequence[str] = (),
    only: Sequence[str] = (),
) -> Team:
    """Fetch a team by id, treating a missing team as a terminal, non-retryable condition.

    Signal workflows are scheduled ahead of the activities that run them, so a team can be
    deleted in between. When that happens the lookup can never succeed: retrying it just burns
    the activity's retry budget and surfaces as error-tracking noise for an outcome that is
    actually expected. Convert the expected ``Team.DoesNotExist`` into a non-retryable
    ``ApplicationError`` so Temporal abandons the activity cleanly instead of retrying it.
    """
    queryset = Team.objects.all()
    if select_related:
        queryset = queryset.select_related(*select_related)
    if only:
        queryset = queryset.only(*only)
    try:
        return await queryset.aget(pk=team_id)
    except Team.DoesNotExist:
        raise temporalio.exceptions.ApplicationError(
            f"Team {team_id} no longer exists; abandoning signals activity",
            type=TEAM_DELETED_ERROR_TYPE,
            non_retryable=True,
        ) from None
