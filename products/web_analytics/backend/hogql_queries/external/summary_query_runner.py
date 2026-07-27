import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any

import chdb
import structlog

from posthog.schema import (
    ExternalQueryError,
    ExternalQueryErrorCode,
    ExternalQueryStatus,
    WebAnalyticsExternalSummaryQuery,
    WebAnalyticsExternalSummaryQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.s3_table import build_function_call
from posthog.hogql.database.schema.web_analytics_s3 import create_s3_web_bounces_table, create_s3_web_stats_table

from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property


@dataclass
class QueryResult:
    rows: list[tuple[str, ...]]

    def first_row(self) -> tuple[str, ...]:
        return self.rows[0] if self.rows else ()


@dataclass
class StatsData:
    unique_visitors: int
    total_sessions: int
    total_pageviews: int


@dataclass
class BouncesData:
    total_bounces: int
    bounce_sessions: int


logger = structlog.get_logger(__name__)


class WebAnalyticsExternalSummaryQueryRunner(QueryRunner):
    query: WebAnalyticsExternalSummaryQuery

    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def _calculate(self) -> WebAnalyticsExternalSummaryQueryResponse:
        if not self.can_use_s3_tables:
            return WebAnalyticsExternalSummaryQueryResponse(
                data={},
                error=ExternalQueryError(
                    code=ExternalQueryErrorCode.PLATFORM_ACCESS_REQUIRED,
                    detail="Organization must have platform access to use external web analytics",
                ),
                status=ExternalQueryStatus.ERROR,
            )

        try:
            stats_result = self._execute_stats_query()
            bounces_result = self._execute_bounces_query()

            results = self._process_query_results(stats_result, bounces_result)

            return WebAnalyticsExternalSummaryQueryResponse(
                data={
                    "unique_visitors": results["unique_visitors"],
                    "total_sessions": results["total_sessions"],
                    "total_pageviews": results["total_pageviews"],
                    "bounce_rate": results["bounce_rate"],
                },
                status=ExternalQueryStatus.SUCCESS,
            )

        except Exception as e:
            logger.error("Platform web analytics query failed", team_id=self.team.pk, error=str(e), exc_info=True)
            return WebAnalyticsExternalSummaryQueryResponse(
                data={},
                error=ExternalQueryError(
                    code=ExternalQueryErrorCode.QUERY_EXECUTION_FAILED,
                    detail="Failed to execute query",
                ),
                status=ExternalQueryStatus.ERROR,
            )

    @cached_property
    def can_use_s3_tables(self) -> bool:
        return bool(self.team.organization.is_platform)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _build_s3_stats_table_func(self) -> str:
        web_stats_table = create_s3_web_stats_table(self.team.pk)
        return build_function_call(
            url=web_stats_table.url,
            format=web_stats_table.format,
            access_key=web_stats_table.access_key,
            access_secret=web_stats_table.access_secret,
            structure=web_stats_table.structure,
        )

    def _build_s3_bounces_table_func(self) -> str:
        web_bounces_table = create_s3_web_bounces_table(self.team.pk)
        return build_function_call(
            url=web_bounces_table.url,
            format=web_bounces_table.format,
            access_key=web_bounces_table.access_key,
            access_secret=web_bounces_table.access_secret,
            structure=web_bounces_table.structure,
        )

    def _execute_stats_query(self) -> QueryResult:
        s3_table_func = self._build_s3_stats_table_func()

        query = f"""
        SELECT
            uniqMerge(persons_uniq_state) as unique_visitors,
            uniqMerge(sessions_uniq_state) as total_sessions,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        rows = [tuple(row) for row in reader]

        return QueryResult(rows=rows)

    def _execute_bounces_query(self) -> QueryResult:
        s3_table_func = self._build_s3_bounces_table_func()

        query = f"""
        SELECT
            sumMerge(bounces_count_state) as total_bounces,
            uniqMerge(sessions_uniq_state) as total_sessions
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        rows = [tuple(row) for row in reader]

        return QueryResult(rows=rows)

    def _parse_stats_data(self, stats_result: QueryResult) -> StatsData:
        row = stats_result.first_row()
        if len(row) < 3:
            return StatsData(unique_visitors=0, total_sessions=0, total_pageviews=0)

        return StatsData(
            unique_visitors=int(row[0]) if row[0] else 0,
            total_sessions=int(row[1]) if row[1] else 0,
            total_pageviews=int(row[2]) if row[2] else 0,
        )

    def _parse_bounces_data(self, bounces_result: QueryResult) -> BouncesData:
        row = bounces_result.first_row()
        if len(row) < 2:
            return BouncesData(total_bounces=0, bounce_sessions=0)

        return BouncesData(
            total_bounces=int(row[0]) if row[0] else 0,
            bounce_sessions=int(row[1]) if row[1] else 0,
        )

    def _process_query_results(self, stats_result: QueryResult, bounces_result: QueryResult) -> dict[str, Any]:
        stats = self._parse_stats_data(stats_result)
        bounces = self._parse_bounces_data(bounces_result)

        bounce_rate = (bounces.total_bounces / bounces.bounce_sessions) if bounces.bounce_sessions > 0 else 0.0

        return {
            "unique_visitors": stats.unique_visitors,
            "total_sessions": stats.total_sessions,
            "total_pageviews": stats.total_pageviews,
            "bounce_rate": round(bounce_rate, 3),
        }
