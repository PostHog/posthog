from datetime import timedelta
from typing import Any

from posthog.schema import HogQLFilters, ProductKey

from posthog.hogql import ast

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.team.team import Team

from .base import Recommendation

TOP_CAUSES_LIMIT = 3


class IngestionFailuresRecommendation(Recommendation):
    type = "ingestion_failures"
    refresh_interval = timedelta(hours=1)

    def compute(self, team: Team) -> dict[str, Any]:
        from posthog.hogql.query import execute_hogql_query

        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            team_id=team.pk,
            name="recommendations:ingestion_failures",
        )

        counts_response = execute_hogql_query(
            query="""
                SELECT
                    countIf(timestamp >= now() - INTERVAL 24 HOUR) AS count_24h,
                    countIf(timestamp >= now() - INTERVAL 1 HOUR) AS count_1h
                FROM events
                WHERE event = '$exception'
                AND timestamp >= now() - INTERVAL 24 HOUR
                AND notEmpty(properties.$cymbal_errors)
                AND {filters}
            """,
            team=team,
            filters=HogQLFilters(filterTestAccounts=True),
        )

        count_24h = 0
        count_1h = 0
        if counts_response.results and counts_response.results[0]:
            count_24h, count_1h = counts_response.results[0]

        top_causes: list[dict[str, Any]] = []
        if count_24h > 0:
            causes_response = execute_hogql_query(
                query="""
                    SELECT
                        arrayJoin(properties.$cymbal_errors) AS cause,
                        count() AS occurrences
                    FROM events
                    WHERE event = '$exception'
                    AND timestamp >= now() - INTERVAL 24 HOUR
                    AND notEmpty(properties.$cymbal_errors)
                    AND {filters}
                    GROUP BY cause
                    ORDER BY occurrences DESC
                    LIMIT {limit}
                """,
                team=team,
                filters=HogQLFilters(filterTestAccounts=True),
                placeholders={"limit": ast.Constant(value=TOP_CAUSES_LIMIT)},
            )
            top_causes = [
                {"cause": cause, "occurrences": occurrences}
                for cause, occurrences in (causes_response.results or [])
                if cause
            ]

        return {
            "count_24h": count_24h,
            "count_1h": count_1h,
            "top_causes": top_causes,
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return (meta.get("count_24h") or 0) == 0
