from functools import cached_property
from typing import cast

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import (
    LogsFilterBuilder,
    LogsQueryResponse,
    LogsQueryRunnerMixin,
    ilike_pattern,
)

# Columns a field may group by. Each value is also the WHERE clause that gets omitted, so a field's
# counts reflect every *other* active filter rather than its own selection.
FIELD_COLUMNS: frozenset[str] = frozenset({"severity_text", "service_name"})

DEFAULT_FIELD_LIMIT = 100


class LogFieldValuesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Per-value counts for a single field, cross-filtered.

    The field is either a top-level column (severity_text/service_name) or a resource attribute map
    key (e.g. k8s.namespace.name). Every active filter is applied except the one belonging to this
    field, so selecting a value re-scopes the *other* fields without zeroing out its own siblings —
    the standard filter-rail behaviour.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        query: LogsQuery,
        *args,
        column: str | None = None,
        resource_attribute: str | None = None,
        field_search: str | None = None,
        **kwargs,
    ):
        super().__init__(query, *args, **kwargs)
        # A field targets either a top-level column (severity_text/service_name) or a resource
        # attribute map key (e.g. k8s.namespace.name). Exactly one must be supplied.
        if bool(column) == bool(resource_attribute):
            raise ValueError("Provide exactly one of column or resource_attribute")
        if column is not None and column not in FIELD_COLUMNS:
            raise ValueError(f"Unsupported field field: {column!r}")
        self.column = column
        self.resource_attribute = resource_attribute
        # Type-ahead over the field's *own* values (e.g. service name contains "kafka"), distinct from
        # query.searchTerm which searches log bodies. Lets a dynamic field search past the LIMIT window.
        self.field_search = (field_search or "").strip() or None

    def _field_expr(self) -> ast.Expr:
        """The expression a field groups by: a top-level column or a resource_attributes map lookup."""
        if self.column is not None:
            return ast.Field(chain=[self.column])
        return ast.Field(chain=["resource_attributes", cast(str, self.resource_attribute)])

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Fail fast rather than scan unbounded data, matching CountQueryRunner.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    def _calculate(self) -> LogsQueryResponse:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )
        results = [{"value": row[0], "count": row[1]} for row in (response.results or [])]
        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        # The day-precision time_bucket prune in where() is widened to exact timestamp bounds so the
        # counts match the requested window (same half-open pattern as CountQueryRunner).
        filter_builder = LogsFilterBuilder(
            self.query,
            self.team,
            self.query_date_range,
            exclude_column=self.column,
            exclude_resource_attribute=self.resource_attribute,
        )
        exprs = [
            filter_builder.where(),
            parse_expr(
                "timestamp >= {date_from} AND timestamp < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                },
            ),
        ]
        if self.resource_attribute is not None:
            # A missing map key reads back as '' in ClickHouse — exclude it so the field doesn't show a
            # blank value counting every log that lacks the attribute.
            exprs.append(parse_expr("{field} != ''", placeholders={"field": self._field_expr()}))
        if self.field_search:
            exprs.append(
                parse_expr(
                    "{field} ILIKE {pattern}",
                    placeholders={
                        "field": self._field_expr(),
                        # Escape %, _ and \ so user input matches literally instead of as wildcards.
                        "pattern": ast.Constant(value=ilike_pattern(self.field_search)),
                    },
                )
            )
        where = ast.And(exprs=exprs)
        query = parse_select(
            """
            SELECT {field} AS value, count() AS count
            FROM logs
            WHERE {where}
            GROUP BY {field}
            ORDER BY count() DESC, {field} ASC
            LIMIT {limit}
            """,
            placeholders={
                "field": self._field_expr(),
                "where": where,
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FIELD_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
