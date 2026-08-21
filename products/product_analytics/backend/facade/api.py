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
from typing import Any
from uuid import UUID

from django.db.models import OuterRef, QuerySet, Subquery
from django.utils.timezone import now

from posthog.models.user import User

from products.product_analytics.backend import insight_test_account_filters, logic
from products.product_analytics.backend.facade.contracts import InsightVariableDefinition
from products.product_analytics.backend.insight_test_account_filters import TestAccountFilterUpdate
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.models.insight_variable import InsightVariable


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
    variables = InsightVariable.objects.filter(team_id=team_id).order_by("name")
    return [_to_variable_definition(variable) for variable in variables]


def insight_variables_by_ids(team_id: int, ids: Collection[str | UUID]) -> list[InsightVariableDefinition]:
    """The team's saved query variables with these ids.

    Ids reach the query as given: a value that is not a UUID raises, rather than being dropped,
    so a caller that accepts unvalidated ids keeps whatever error it raises today.
    """
    if not ids:
        return []
    variables = InsightVariable.objects.filter(team_id=team_id, id__in=ids)
    return [_to_variable_definition(variable) for variable in variables]


def insight_variables_by_code_names(team_id: int, code_names: Collection[str]) -> list[InsightVariableDefinition]:
    """The team's saved query variables with these code names."""
    if not code_names:
        return []
    variables = InsightVariable.objects.filter(team_id=team_id, code_name__in=code_names)
    return [_to_variable_definition(variable) for variable in variables]


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
    variable = InsightVariable.objects.create(
        team_id=team_id,
        name=name,
        type=type,
        code_name=code_name,
        default_value=default_value,
        is_multi=is_multi,
    )
    return _to_variable_definition(variable)


def record_insight_view(*, insight_id: int, team_id: int | None = None, user_id: int | None = None) -> None:
    """Mark an insight as viewed now, moving the timestamp if this viewer already has a row.

    Shared and embedded renders have no viewer, so ``team_id`` and ``user_id`` are both optional:
    left out, the view is recorded against the anonymous row for the insight.
    """
    InsightViewed.objects.update_or_create(
        insight_id=insight_id, team_id=team_id, user_id=user_id, defaults={"last_viewed_at": now()}
    )


def record_insight_views(
    *, team_id: int | None, user_id: int | None, last_viewed_at_by_insight_id: Mapping[int, datetime]
) -> None:
    """Record one view per insight in a single insert. Runs in the caller's transaction.

    No conflict handling: a viewer that already has a row for one of these insights makes the
    whole insert fail, which is the caller's to catch.
    """
    InsightViewed.objects.bulk_create(
        InsightViewed(team_id=team_id, user_id=user_id, insight_id=insight_id, last_viewed_at=last_viewed_at)
        for insight_id, last_viewed_at in last_viewed_at_by_insight_id.items()
    )


def refresh_insight_views(*, team_id: int, user_id: int, insight_ids: Collection[int]) -> None:
    """Mark every one of these insights as viewed now by this viewer, in a single statement.

    Unlike ``record_insight_views``, a viewer who already has a row for one of the insights keeps
    it and gets the timestamp moved forward.
    """
    if not insight_ids:
        return
    viewed_at = now()
    InsightViewed.objects.bulk_create(
        [
            InsightViewed(team_id=team_id, user_id=user_id, insight_id=insight_id, last_viewed_at=viewed_at)
            for insight_id in insight_ids
        ],
        update_conflicts=True,
        unique_fields=["team", "user", "insight"],
        update_fields=["last_viewed_at"],
    )


def with_last_viewed_at(insights: QuerySet) -> QuerySet:
    """Annotate an insight queryset with ``last_viewed_at``, the most recent view by anyone."""
    last_viewed_at = (
        InsightViewed.objects.filter(insight=OuterRef("pk")).order_by("-last_viewed_at").values("last_viewed_at")[:1]
    )
    return insights.annotate(last_viewed_at=Subquery(last_viewed_at))


def recently_viewed_insights(*, team_id: int, user_id: int, limit: int) -> list[Insight]:
    """The insights this viewer looked at most recently, newest first, deleted ones left out.

    Each one carries the viewer's own ``last_viewed_at`` rather than the team-wide latest.
    """
    views = (
        InsightViewed.objects.filter(team_id=team_id, user_id=user_id)
        .select_related("insight")
        .exclude(insight__deleted=True)
        .only("insight", "last_viewed_at")
        .order_by("-last_viewed_at")[:limit]
    )

    recently_viewed = []
    for view in views:
        insight = view.insight
        insight.last_viewed_at = view.last_viewed_at
        recently_viewed.append(insight)
    return recently_viewed


def recent_viewers_by_insight(
    *, team_id: int, insight_ids: Collection[int], since: datetime, max_per_insight: int
) -> dict[int, list[User]]:
    """The people who most recently looked at each of these insights, newest first.

    One query for the whole batch, so a caller rendering a list of insights does not go per-row.
    """
    if not insight_ids:
        return {}
    views = (
        InsightViewed.objects.filter(
            team_id=team_id,
            insight_id__in=insight_ids,
            last_viewed_at__gte=since,
            user__isnull=False,
        )
        .select_related("user")
        .order_by("insight_id", "-last_viewed_at")
    )

    viewers_by_insight: dict[int, list[User]] = {}
    for view in views:
        if view.user is None:
            continue
        bucket = viewers_by_insight.setdefault(view.insight_id, [])
        if len(bucket) < max_per_insight:
            bucket.append(view.user)
    return viewers_by_insight


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariableDefinition]) -> dict:
    """Refresh an insight's stored variables against the team's latest variable definitions."""
    return logic.map_stale_to_latest(stale_variables, latest_variables)


def plan_test_account_filter_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Work out how to set the test account filter on an insight, without touching the stored query."""
    return insight_test_account_filters.plan_test_account_filter_update(query, enabled=enabled)


def get_query_specific_instructions(kind: str) -> str:
    """Analysis guidance for a query kind, used by LLM insight and subscription summaries."""
    return logic.get_query_specific_instructions(kind)
