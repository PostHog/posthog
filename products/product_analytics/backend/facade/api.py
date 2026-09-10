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

import math
from collections.abc import Collection, Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import QuerySet

from products.product_analytics.backend import logic
from products.product_analytics.backend.facade.contracts import (
    InsightVariableDefinition,
    SavedInsightIdentity,
    SavedInsightMeasurement,
)
from products.product_analytics.backend.facade.models import resolve_insight_by_id_or_short_id
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


def saved_insight_identity(*, team_id: int, reference: str | int) -> SavedInsightIdentity | None:
    """Resolve one live saved insight without exposing its model across the product boundary."""

    insight = resolve_insight_by_id_or_short_id(
        Insight.objects.filter(team_id=team_id, saved=True, deleted=False), reference
    )
    if insight is None or insight.team_id != team_id or insight.deleted or not insight.saved:
        return None
    return SavedInsightIdentity(
        id=insight.id,
        short_id=insight.short_id,
        team_id=insight.team_id,
        last_modified_at=insight.last_modified_at,
    )


def measure_saved_insight_trends(
    *,
    team_id: int,
    insight_id: int,
    short_id: str,
    last_modified_at: datetime,
    frozen_query: Mapping[str, object],
    date_from: datetime,
    date_to: datetime,
) -> SavedInsightMeasurement:
    """Read one frozen Trends total after re-checking saved-insight authority.

    The supplied query is a canonical snapshot with no date range. This boundary owns
    the saved/deleted/team/version checks and is the sole place a cross-product caller
    can invoke the blocking query service for a saved insight.
    """
    insight = (
        Insight.objects_including_soft_deleted.filter(
            id=insight_id,
            team_id=team_id,
            saved=True,
            deleted=False,
        )
        .only("id", "short_id", "team_id", "last_modified_at")
        .first()
    )
    if insight is None:
        return SavedInsightMeasurement(status="insight_not_found")
    if insight.short_id != short_id or insight.last_modified_at != last_modified_at:
        return SavedInsightMeasurement(status="insight_authority_changed")

    from pydantic import ValidationError

    from posthog.schema import DateRange, TrendsQuery

    from posthog.api.services.query import process_query_model

    try:
        query = TrendsQuery.model_validate(frozen_query)
    except ValidationError:
        return SavedInsightMeasurement(status="response_unsupported")
    if query.dateRange is not None:
        return SavedInsightMeasurement(status="response_unsupported")
    query = query.model_copy(
        update={"dateRange": DateRange(date_from=date_from.date().isoformat(), date_to=date_to.date().isoformat())}
    )
    try:
        response = process_query_model(insight.team, query, insight_id=insight.id)
    except Exception:
        return SavedInsightMeasurement(status="query_error")
    value = _finite_single_trends_total(response)
    if value is None:
        return SavedInsightMeasurement(status="response_unsupported")
    return SavedInsightMeasurement(status="success", value=value)


def _finite_single_trends_total(response: object) -> Decimal | None:
    results = getattr(response, "results", None)
    if results is None and isinstance(response, Mapping):
        results = response.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], Mapping):
        return None
    count = results[0].get("count")
    if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count):
        return None
    value = Decimal(str(count))
    return value if value.is_finite() else None


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


def insights_including_soft_deleted_for_team(*, team_id: int, insight_ids: Collection[int]) -> list[Insight]:
    return logic.insights_including_soft_deleted_for_team(team_id=team_id, insight_ids=insight_ids)


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
