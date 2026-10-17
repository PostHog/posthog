from math import isfinite
from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import (
    CompareFilter,
    DateRange,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
    MarketingAnalyticsSearchSource,
)


class SearchRecommendationsQuery(BaseModel):
    sources: list[MarketingAnalyticsSearchSource] = Field(
        description="Connected search source tables from the search report."
    )
    breakdown: Literal["keyword", "page"] | None = None
    compareFilter: CompareFilter | None = None
    dateRange: DateRange | None = None
    keyword: str | None = None
    page: str | None = None
    search: str | None = None
    normalizePageUrls: bool | None = None


class SearchRecommendation(BaseModel):
    row: MarketingAnalyticsSearchRow
    kind: Literal["spend_without_conversions", "higher_cpa", "lower_organic_ctr"]
    current: float
    previous: float


class SearchRecommendations(BaseModel):
    recommendations: list[SearchRecommendation] = Field(default_factory=list)
    goal_id: str | None = None
    warning: str | None = None


def search_recommendations(
    response: MarketingAnalyticsSearchQueryResponse, goal_id: str | None
) -> SearchRecommendations:
    result = SearchRecommendations(goal_id=goal_id)
    if goal_id and (
        response.posthogConversionsWarning or goal_id not in {goal.id for goal in response.posthogConversionGoals or []}
    ):
        result.warning = response.posthogConversionsWarning or "The selected PostHog conversion goal is unavailable."
        return result
    for row in response.results:
        previous = row.previous
        if previous is None or not all(
            isfinite(value) and value >= 0
            for value in (row.clicks, row.impressions, previous.clicks, previous.impressions)
        ):
            continue
        if row.platform == "GoogleSearchConsole":
            if row.impressions >= 1000 and previous.impressions >= 1000 and previous.clicks >= 30:
                current_ctr = row.clicks / row.impressions
                previous_ctr = previous.clicks / previous.impressions
                if current_ctr <= previous_ctr * 0.7:
                    result.recommendations.append(
                        SearchRecommendation(
                            row=row, kind="lower_organic_ctr", current=current_ctr, previous=previous_ctr
                        )
                    )
            continue
        if not row.currency or not all(
            value is not None and isfinite(value) and value > 0 for value in (row.cost, previous.cost)
        ):
            continue
        goal = next((goal for goal in row.posthogConversions or [] if goal.id == goal_id), None)
        conversions = (goal.conversions if goal else None) if goal_id else row.conversions
        previous_conversions = (goal.previousConversions if goal else None) if goal_id else previous.conversions
        if (
            conversions is None
            or previous_conversions is None
            or not isfinite(conversions)
            or not isfinite(previous_conversions)
            or conversions < 0
            or previous_conversions < 5
        ):
            continue
        if conversions == 0 and row.clicks >= 100:
            result.recommendations.append(
                SearchRecommendation(
                    row=row, kind="spend_without_conversions", current=0, previous=previous_conversions
                )
            )
        elif conversions >= 10 and previous_conversions >= 10 and row.cost is not None and previous.cost is not None:
            current_cpa = row.cost / conversions
            previous_cpa = previous.cost / previous_conversions
            if current_cpa >= previous_cpa * 1.5:
                result.recommendations.append(
                    SearchRecommendation(row=row, kind="higher_cpa", current=current_cpa, previous=previous_cpa)
                )
    result.recommendations = result.recommendations[:5]
    return result
