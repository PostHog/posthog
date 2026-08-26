from collections.abc import Collection, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import OuterRef, QuerySet, Subquery
from django.utils.timezone import now

from products.product_analytics.backend.facade.contracts import InsightVariableDefinition
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.models.insight_variable import InsightVariable

if TYPE_CHECKING:
    from posthog.models.user import User

# The columns `InsightVariableDefinition` carries; `values` and `values_query` stay on the row.
VARIABLE_DEFINITION_FIELDS = ("id", "name", "code_name", "type", "default_value", "is_multi")


def insight_variables_for_team(team_id: int) -> QuerySet[InsightVariable]:
    return InsightVariable.objects.filter(team_id=team_id).only(*VARIABLE_DEFINITION_FIELDS).order_by("name")


def insight_variables_by_ids(team_id: int, ids: Collection[str | UUID]) -> QuerySet[InsightVariable]:
    return InsightVariable.objects.filter(team_id=team_id, id__in=ids).only(*VARIABLE_DEFINITION_FIELDS)


def insight_variables_by_code_names(team_id: int, code_names: Collection[str]) -> QuerySet[InsightVariable]:
    return InsightVariable.objects.filter(team_id=team_id, code_name__in=code_names).only(*VARIABLE_DEFINITION_FIELDS)


def create_insight_variable(
    *, team_id: int, name: str, type: str, code_name: str | None, default_value: Any, is_multi: bool
) -> InsightVariable:
    return InsightVariable.objects.create(
        team_id=team_id, name=name, type=type, code_name=code_name, default_value=default_value, is_multi=is_multi
    )


def record_insight_view(*, insight_id: int, team_id: int | None, user_id: int | None) -> None:
    InsightViewed.objects.update_or_create(
        insight_id=insight_id, team_id=team_id, user_id=user_id, defaults={"last_viewed_at": now()}
    )


def record_insight_views(*, team_id: int, user_id: int, last_viewed_at_by_insight_id: Mapping[int, datetime]) -> None:
    InsightViewed.objects.bulk_create(
        [
            InsightViewed(team_id=team_id, user_id=user_id, insight_id=insight_id, last_viewed_at=last_viewed_at)
            for insight_id, last_viewed_at in last_viewed_at_by_insight_id.items()
        ],
        update_conflicts=True,
        unique_fields=["team", "user", "insight"],
        update_fields=["last_viewed_at"],
    )


def with_last_viewed_at(insights: QuerySet) -> QuerySet:
    last_viewed_at = (
        InsightViewed.objects.filter(insight=OuterRef("pk")).order_by("-last_viewed_at").values("last_viewed_at")[:1]
    )
    return insights.annotate(last_viewed_at=Subquery(last_viewed_at))


def recently_viewed_insights(*, team_id: int, user_id: int, limit: int) -> list[Insight]:
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
) -> dict[int, list["User"]]:
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
    # Keep the variables in an insight up to date based on variable code names that exist
    current_variables = stale_variables
    insight_variables = latest_variables
    final_variables = {}

    # Create a lookup for insight variables by code_name for quick access
    insight_variables_by_code_name = {var.code_name: var for var in insight_variables}

    # For each variable in current_variables, update with data from insight_variables if code_name matches
    for _, v in current_variables.items():
        code_name = v.get("code_name")
        if code_name in insight_variables_by_code_name:
            # Update the variable with corresponding data from insight_variables
            matched_var = insight_variables_by_code_name[code_name]
            # Add attributes from matched_var that can be serialized to JSON
            final_variables[str(matched_var.id)] = {
                **v,
                "code_name": matched_var.code_name,
                "variableId": str(matched_var.id),
            }

    return final_variables


def get_query_specific_instructions(kind: str) -> str:
    if kind == "TrendsQuery":
        return (
            "Focus on identifying significant changes in volume, growth trends, and seasonality. "
            "Compare the current period to the start. Identify which breakdown segment (if any) is driving the trend."
        )
    elif kind == "FunnelsQuery":
        return (
            "Focus on conversion rates between steps. When there are three or more steps, name the step-to-step "
            "transition with the largest loss. When there are only two steps (one transition), describe the single "
            "drop-off directly without superlatives like 'the biggest' or 'the main bottleneck' — there is nothing "
            "to compare it against. Compare conversion across breakdown segments if available."
        )
    elif kind == "RetentionQuery":
        return (
            "Focus on the retention curve shape. Identify when the drop-off stabilizes. "
            "Compare retention rates between different cohorts or breakdown segments."
        )
    elif kind == "StickinessQuery":
        return "Focus on how frequently users engage. Identify if there is a core group of power users."
    elif kind == "LifecycleQuery":
        return "Focus on the balance between new, returning, resurrecting, and dormant users. Identify which group is dominating the total count."

    return "Focus on the most significant patterns and anomalies in the data."
