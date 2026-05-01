import datetime as dt
from zoneinfo import ZoneInfo

from posthog.schema import IntervalType, LogAttributeResult, LogAttributesQuery, LogAttributesQueryResponse, MatchedOn

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property

from products.logs.backend.logs_query_runner import LogsQueryRunnerMixin

# Read a max of 5GB from the table at a time - this should get us plenty of results
# without having long and expensive attributes queries. Users can always search or add other
# filters to narrow things down (and will likely have to anyway if we're returning thousands of attributes)
MAX_READ_BYTES = 5_000_000_000

# Value-search probes attribute_value with ILIKE %search%, which scans far more rows than
# the key-only path. Require a meaningfully specific term so short prefixes (e.g. "id")
# don't trigger an expensive scan.
MIN_VALUE_SEARCH_LENGTH = 4


class LogAttributesQueryRunner(AnalyticsQueryRunner[LogAttributesQueryResponse], LogsQueryRunnerMixin):
    query: LogAttributesQuery

    def __init__(self, query: LogAttributesQuery, *args, **kwargs):
        super().__init__(query, *args, **kwargs)
        self.query = query
        self.modifiers.convertToProjectTimezone = False

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=10,
            now=dt.datetime.now(),
            timezone_info=ZoneInfo("UTC"),
        )

    def to_query(self) -> ast.SelectQuery:
        if self._should_search_values():
            return self._to_query_with_value_search()
        return self._to_query_keys_only()

    def _should_search_values(self) -> bool:
        if not self.query.searchValues or not self.query.search:
            return False
        return len(self.query.search) >= MIN_VALUE_SEARCH_LENGTH

    def _to_query_keys_only(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                groupArray({limit})(attribute_key) as keys,
                count() as total_count
            FROM (
                SELECT
                    attribute_key,
                    sum(attribute_count)
                FROM log_attributes
                WHERE time_bucket >= {date_from_start_of_interval}
                AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
                AND attribute_type = {attributeType}
                AND attribute_key ILIKE {search}
                AND {where}
                GROUP BY team_id, attribute_key
                ORDER BY lower(attribute_key) = lower({exact}) DESC, has(splitByNonAlpha(lower(attribute_key)), lower({exact})) DESC, sum(attribute_count) desc, attribute_key asc
                OFFSET {offset}
            )
            """,
            placeholders={
                "search": ast.Constant(value=f"%{self.query.search}%"),
                "exact": ast.Constant(value=self.query.search),
                "attributeType": ast.Constant(value=self.query.attributeType),
                "limit": ast.Constant(value=self.query.limit),
                "offset": ast.Constant(value=self.query.offset),
                "where": self.where(),
                **self.query_date_range.to_placeholders(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _to_query_with_value_search(self) -> ast.SelectQuery:
        # UNION ALL of two branches:
        #   (1) keys whose name matches the search
        #   (2) keys whose values match the search but whose name does NOT match
        # The NOT-ILIKE on the value branch dedupes — a key never appears twice.
        # match_type lets the outer ORDER BY put key matches above value matches.
        query = parse_select(
            """
            SELECT
                attribute_key,
                match_type,
                sample_value,
                total_count
            FROM (
                SELECT
                    attribute_key,
                    'key' AS match_type,
                    '' AS sample_value,
                    sum(attribute_count) AS total_count
                FROM log_attributes
                WHERE time_bucket >= {date_from_start_of_interval}
                AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
                AND attribute_type = {attributeType}
                AND attribute_key ILIKE {search}
                AND {where}
                GROUP BY team_id, attribute_key

                UNION ALL

                SELECT
                    attribute_key,
                    'value' AS match_type,
                    argMax(attribute_value, attribute_count) AS sample_value,
                    sum(attribute_count) AS total_count
                FROM log_attributes
                WHERE time_bucket >= {date_from_start_of_interval}
                AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
                AND attribute_type = {attributeType}
                AND attribute_value ILIKE {search}
                AND attribute_key NOT ILIKE {search}
                AND {where}
                GROUP BY team_id, attribute_key
            )
            ORDER BY
                match_type = 'key' DESC,
                lower(attribute_key) = lower({exact}) DESC,
                has(splitByNonAlpha(lower(attribute_key)), lower({exact})) DESC,
                total_count DESC,
                attribute_key ASC
            LIMIT {limit}
            OFFSET {offset}
            """,
            placeholders={
                "search": ast.Constant(value=f"%{self.query.search}%"),
                "exact": ast.Constant(value=self.query.search),
                "attributeType": ast.Constant(value=self.query.attributeType),
                "limit": ast.Constant(value=self.query.limit),
                "offset": ast.Constant(value=self.query.offset),
                "where": self.where(),
                **self.query_date_range.to_placeholders(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def where(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        exprs.append(self.resource_filter(existing_filters=exprs))

        return ast.And(exprs=exprs)

    def _calculate(self) -> LogAttributesQueryResponse:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            settings=self.settings,
        )

        property_filter_type = "log_resource_attribute" if self.query.attributeType == "resource" else "log_attribute"

        if self._should_search_values():
            return self._format_value_search_response(response, property_filter_type)
        return self._format_keys_only_response(response, property_filter_type)

    def _format_keys_only_response(self, response, property_filter_type: str) -> LogAttributesQueryResponse:
        if not (isinstance(response.results, list) and len(response.results) > 0 and len(response.results[0]) > 0):
            return LogAttributesQueryResponse(results=[], count=0)

        formatted_results: list[LogAttributeResult] = []
        for result in response.results[0][0]:
            formatted_results.append(
                LogAttributeResult(
                    name=result,
                    propertyFilterType=property_filter_type,
                    matchedOn=MatchedOn.KEY,
                )
            )

        total_count = response.results[0][1] + (self.query.offset or 0)
        return LogAttributesQueryResponse(results=formatted_results, count=total_count)

    def _format_value_search_response(self, response, property_filter_type: str) -> LogAttributesQueryResponse:
        if not isinstance(response.results, list):
            return LogAttributesQueryResponse(results=[], count=0)

        formatted_results: list[LogAttributeResult] = []
        for row in response.results:
            attribute_key, match_type, sample_value, _total_count = row
            matched_on_key = match_type == "key"
            formatted_results.append(
                LogAttributeResult(
                    name=attribute_key,
                    propertyFilterType=property_filter_type,
                    matchedOn=MatchedOn.KEY if matched_on_key else MatchedOn.VALUE,
                    matchedValue=None if matched_on_key else (sample_value or None),
                )
            )

        # Total count for value-search isn't separately computed; use returned page size
        # plus offset as a lower bound. The frontend uses this only to decide whether to
        # show a "load more" affordance, so an exact count isn't required.
        return LogAttributesQueryResponse(
            results=formatted_results,
            count=len(formatted_results) + (self.query.offset or 0),
        )

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            # "break" means return partial results if we hit the read limit
            read_overflow_mode="break",
            max_bytes_to_read=MAX_READ_BYTES,
        )
