"""
Facade for product_analytics.

The public entry point core and other products import product-analytics
functionality from; ``facade.models`` carries the sanctioned model-class
crossings. Functions here stay thin and delegate to ``backend.logic``.

Saved query variables and insight-view tracking cross as data: callers pass a team id and get
``InsightVariableDefinition`` contracts back, so no caller has to hold ``InsightVariable`` or
``InsightViewed``. Variable reads scope by ``team_id=``, which ``RootTeamMixin`` widens to the
project's root team, because that is the team ``RootTeamMixin.save()`` writes the rows against.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import QuerySet

from products.product_analytics.backend import logic
from products.product_analytics.backend.facade.contracts import InsightVariableDefinition
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable

if TYPE_CHECKING:
    from posthog.models.user import User


def _to_variable_definition(variable: InsightVariable) -> InsightVariableDefinition:
    return InsightVariableDefinition(
        id=variable.id,
        name=variable.name,
        code_name=variable.code_name,
        type=variable.type,
        default_value=variable.default_value,
        is_multi=variable.is_multi,
    )


def insight_variables_for_team(team_id: int) -> list[InsightVariableDefinition]:
    """Every saved query variable on the team's project, ordered by name."""
    return [_to_variable_definition(variable) for variable in logic.insight_variables_for_team(team_id)]


def insight_variables_by_ids(team_id: int, ids: Collection[str | UUID]) -> list[InsightVariableDefinition]:
    """The team's saved query variables with these ids.

    Ids reach the query as given: a value that is not a UUID raises, rather than being dropped,
    so a caller that accepts unvalidated ids keeps whatever error it raises today.
    """
    return [_to_variable_definition(variable) for variable in logic.insight_variables_by_ids(team_id, ids)]


def insight_variables_by_code_names(team_id: int, code_names: Collection[str]) -> list[InsightVariableDefinition]:
    """The team's saved query variables with these code names."""
    return [
        _to_variable_definition(variable) for variable in logic.insight_variables_by_code_names(team_id, code_names)
    ]


def create_insight_variable(
    *,
    team_id: int,
    name: str,
    type: str,
    code_name: str | None = None,
    default_value: Any = None,
    is_multi: bool = False,
) -> InsightVariableDefinition:
    """Add a saved query variable to the team. Runs in the caller's transaction."""
    variable = logic.create_insight_variable(
        team_id=team_id, name=name, type=type, code_name=code_name, default_value=default_value, is_multi=is_multi
    )
    return _to_variable_definition(variable)


def record_insight_view(*, insight_id: int, team_id: int | None = None, user_id: int | None = None) -> None:
    """Mark an insight as viewed now, moving the timestamp if this viewer already has a row.

    Shared and embedded renders have no viewer, so ``team_id`` and ``user_id`` are both optional:
    left out, the view is recorded against the anonymous row for the insight.
    """
    logic.record_insight_view(insight_id=insight_id, team_id=team_id, user_id=user_id)


def record_insight_views(*, team_id: int, user_id: int, last_viewed_at_by_insight_id: Mapping[int, datetime]) -> None:
    """Record this viewer's view of each insight at the given time, in a single statement.

    A viewer who already has a row for one of the insights keeps it and gets the timestamp moved.
    Runs in the caller's transaction.
    """
    logic.record_insight_views(
        team_id=team_id, user_id=user_id, last_viewed_at_by_insight_id=last_viewed_at_by_insight_id
    )


def with_last_viewed_at(insights: QuerySet) -> QuerySet:
    """Annotate an insight queryset with ``last_viewed_at``, the most recent view by anyone."""
    return logic.with_last_viewed_at(insights)


def recently_viewed_insights(*, team_id: int, user_id: int, limit: int) -> list[Insight]:
    """The insights this viewer looked at most recently, newest first, deleted ones left out.

    Each one carries the viewer's own ``last_viewed_at`` rather than the team-wide latest.
    """
    return logic.recently_viewed_insights(team_id=team_id, user_id=user_id, limit=limit)


def recent_viewers_by_insight(
    *, team_id: int, insight_ids: Collection[int], since: datetime, max_per_insight: int
) -> dict[int, list["User"]]:
    """The people who most recently looked at each of these insights, newest first.

    One query for the whole batch, so a caller rendering a list of insights does not go per-row.
    """
    return logic.recent_viewers_by_insight(
        team_id=team_id, insight_ids=insight_ids, since=since, max_per_insight=max_per_insight
    )


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariableDefinition]) -> dict:
    """Refresh an insight's stored variables against the team's latest variable definitions."""
    return logic.map_stale_to_latest(stale_variables, latest_variables)


def get_query_specific_instructions(kind: str) -> str:
    """Analysis guidance for a query kind, used by LLM insight and subscription summaries."""
    return logic.get_query_specific_instructions(kind)
