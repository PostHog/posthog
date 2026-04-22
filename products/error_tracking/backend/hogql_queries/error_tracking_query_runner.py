import datetime
from zoneinfo import ZoneInfo

import structlog

from posthog.schema import CachedErrorTrackingQueryResponse, ErrorTrackingQuery, ErrorTrackingQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v1 import ErrorTrackingQueryV1Builder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v2 import ErrorTrackingQueryV2Builder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v3 import ErrorTrackingQueryV3Builder

logger = structlog.get_logger(__name__)


class ErrorTrackingQueryRunner(AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingQuery
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    CACHE_VERSION = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        self.date_from = ErrorTrackingQueryRunner.parse_relative_date_from(self.query.dateRange.date_from)
        self.date_to = ErrorTrackingQueryRunner.parse_relative_date_to(self.query.dateRange.date_to)

        if self.query.withAggregations is None:
            self.query.withAggregations = True

        if self.query.withFirstEvent is None:
            self.query.withFirstEvent = True

        if self.query.withLastEvent is None:
            self.query.withLastEvent = False

    @cached_property
    def _builder(self) -> ErrorTrackingQueryV1Builder | ErrorTrackingQueryV2Builder | ErrorTrackingQueryV3Builder:
        if self.query.useQueryV3:
            return ErrorTrackingQueryV3Builder(self.query, self.date_from, self.date_to)
        if self.query.useQueryV2:
            return ErrorTrackingQueryV2Builder(self.query, self.date_from, self.date_to)
        return ErrorTrackingQueryV1Builder(self.query, self.team, self.date_from, self.date_to)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["error_tracking_cache_version"] = self.CACHE_VERSION
        return payload

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=365 * 4)
        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")
        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery:
        return self._builder.build_query()

    def _calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self._builder.build_query(),
                team=self.team,
                query_type="ErrorTrackingQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                filters=self._builder.hogql_filters(),
                user=self.user,
            )

        columns: list[str] = query_result.columns or []

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=self._builder.process_results(columns, query_result.results),
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
