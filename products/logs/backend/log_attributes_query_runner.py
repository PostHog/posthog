import datetime as dt

from posthog.schema import IntervalType, LogAttributesQuery, LogAttributesQueryResponse

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
        )

    def to_query(self) -> ast.SelectQuery:
        # temporarily exclude resource_attributes from the log attributes results
        # this is because we are currently merging resource attributes into log attributes but will stop soon
        # once we stop merging the attributes here: https://github.com/PostHog/posthog/blob/d55f534193220eee1cd50df2c4465229925a572d/rust/capture-logs/src/log_record.rs#L91
        # and the 7 day retention period has passed, we can remove this code
        # If you see this message after 2026-01-01 tell @frank to do it already
        exclude_expression: ast.Expr = ast.Constant(value=1)
        if self.query.attributeType == "log":
            exclude_expression = parse_expr(
                """(attribute_key) NOT IN (
                    SELECT attribute_key FROM log_attributes
                    WHERE time_bucket >= {date_from_start_of_interval}
                    AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
                    AND attribute_type = 'resource'
                    AND attribute_key LIKE {search}
                    AND {where}
                )""",
                placeholders={
                    "search": ast.Constant(value=f"%{self.query.search}%"),
                    **self.query_date_range.to_placeholders(),
                    "where": self.where(),
                },
            )

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
                AND attribute_key LIKE {search}
                AND {exclude_expression}
                AND {where}
                GROUP BY team_id, attribute_key
                ORDER BY sum(attribute_count) desc, attribute_key asc
                OFFSET {offset}
            )
            """,
            placeholders={
                "search": ast.Constant(value=f"%{self.query.search}%"),
                "attributeType": ast.Constant(value=self.query.attributeType),
                "exclude_expression": exclude_expression,
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

        formatted_results = []
        if isinstance(response.results, list) and len(response.results) > 0 and len(response.results[0]) > 0:
            for result in response.results[0][0]:
                entry = {
                    "name": result,
                    "propertyFilterType": "log_resource_attribute"
                    if self.query.attributeType == "resource"
                    else "log_attribute",
                }
                formatted_results.append(entry)

            total_count = response.results[0][1] + self.query.offset
            return LogAttributesQueryResponse(results=formatted_results, count=total_count)
        return LogAttributesQueryResponse(results=[], count=0)

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            # "break" means return partial results if we hit the read limit
            read_overflow_mode="break",
            max_bytes_to_read=MAX_READ_BYTES,
        )
