from typing import Optional, cast

from posthog.schema import InsightActorsQuery, TrendsQuery

from posthog.hogql import ast

from posthog.models import Team

from products.product_analytics.backend.facade.contracts import TrendsActorsDateWindow
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner


def trends_actors_date_window(*, team: Team, query: InsightActorsQuery) -> TrendsActorsDateWindow:
    """The window of the events that the actors query for a Trends data point counts.

    Raises ``ValueError`` when the query's source is not a Trends query, and ``QueryError`` when the query's
    ``day`` does not suit the insight's display.
    """
    if not isinstance(query.source, TrendsQuery):
        raise ValueError(f"Expected a Trends query source, got {query.source.kind}")
    # The runner can rewrite its query's breakdown, so it gets a copy.
    window = TrendsQueryRunner(query=query.source.model_copy(deep=True), team=team).to_actors_date_window(
        time_frame=cast(Optional[str], query.day),  # Trends data points are dates, never integers
        series_index=query.series or 0,
        compare_value=query.compare,
    )
    return TrendsActorsDateWindow(
        date_from=window.from_datetime,
        date_to=window.to_datetime,
        date_to_inclusive=window.to_op == ast.CompareOperationOp.LtEq,
    )
