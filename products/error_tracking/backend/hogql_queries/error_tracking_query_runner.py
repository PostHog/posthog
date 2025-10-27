import re
import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError

import structlog

from posthog.schema import (
    CachedErrorTrackingQueryResponse,
    DateRange,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    HogQLFilters,
    RevenueEntity,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property.util import property_to_django_filter
from posthog.utils import relative_date_parse

from products.error_tracking.backend.api.issues import ErrorTrackingIssueSerializer
from products.error_tracking.backend.models import ErrorTrackingIssue

logger = structlog.get_logger(__name__)


@dataclass
class VolumeOptions:
    date_range: DateRange
    resolution: int


class ErrorTrackingQueryRunner(AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingQuery
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

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

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        """
        Parses a relative date string into a datetime object.
        This is used to convert the date range from the query into a datetime object.
        """
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=365 * 4)  # 4 years ago

        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        """
        Parses a relative date string into a datetime object.
        This is used to convert the date range from the query into a datetime object.
        """
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")

        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery:
        inner_select, outer_select = map(list, zip(*self.select_pairs()))
        order_by = [ast.OrderExpr(expr=ast.Field(chain=[self.query.orderBy]), order=self.order_direction)]
        group_by: list[ast.Expr] = [ast.Field(chain=["id"])]

        events_select = ast.SelectQuery(
            select=inner_select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=self.where,
        )

        if not self.sort_by_revenue:
            events_select.group_by = group_by
            events_select.order_by = order_by
            return events_select

        group_by.append(self.revenue_entity_field)
        events_select.group_by = group_by

        return ast.SelectQuery(
            select=outer_select,
            select_from=ast.JoinExpr(table=events_select, alias="per_issue_per_revenue_entity"),
            group_by=[ast.Field(chain=["id"])],
            order_by=order_by,
        )

    def select_pairs(self):
        expr_pairs = [
            [ast.Alias(alias="id", expr=ast.Field(chain=["issue_id"])), ast.Field(chain=["id"])],
            [
                ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
                ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["last_seen"])])),
            ],
            [
                ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
                ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["first_seen"])])),
            ],
        ]

        if self.query.withAggregations:
            expr_pairs.extend(
                [
                    [
                        ast.Alias(
                            alias="occurrences",
                            expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["uuid"])]),
                        ),
                        ast.Alias(
                            alias="occurrences", expr=ast.Call(name="sum", args=[ast.Field(chain=["occurrences"])])
                        ),
                    ],
                    [
                        ast.Alias(
                            alias="sessions",
                            expr=ast.Call(
                                name="count",
                                distinct=True,
                                # the $session_id property can be blank if not set
                                # we do not want that case counted so cast it to `null` which is excluded by default
                                args=[
                                    ast.Call(
                                        name="nullIf", args=[ast.Field(chain=["$session_id"]), ast.Constant(value="")]
                                    )
                                ],
                            ),
                        ),
                        ast.Alias(alias="sessions", expr=ast.Call(name="sum", args=[ast.Field(chain=["sessions"])])),
                    ],
                    [
                        ast.Alias(
                            alias="users",
                            expr=ast.Call(
                                name="count",
                                distinct=True,
                                args=[self.revenue_entity_field],
                            ),
                        ),
                        ast.Alias(alias="users", expr=ast.Call(name="sum", args=[ast.Field(chain=["users"])])),
                    ],
                    [
                        ast.Alias(
                            alias="volumeRange",
                            expr=self.select_sparkline_array(self.date_from, self.date_to, self.query.volumeResolution),
                        ),
                        ast.Alias(
                            alias="volumeRange",
                            expr=ast.Call(name="sumForEach", args=[ast.Field(chain=["volumeRange"])]),
                        ),
                    ],
                ]
            )

        if self.query.withFirstEvent:
            expr_pairs.append(
                [
                    ast.Alias(
                        alias="first_event",
                        expr=ast.Call(
                            name="argMin",
                            args=[
                                ast.Tuple(
                                    exprs=[
                                        ast.Field(chain=["uuid"]),
                                        ast.Field(chain=["timestamp"]),
                                        ast.Field(chain=["properties"]),
                                    ]
                                ),
                                ast.Field(chain=["timestamp"]),
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="first_event",
                        expr=ast.Call(
                            name="argMin",
                            args=[
                                ast.Field(chain=["first_event"]),
                                ast.Field(chain=["per_issue_per_revenue_entity", "first_seen"]),
                            ],
                        ),
                    ),
                ]
            )

        if self.query.withLastEvent:
            expr_pairs.append(
                [
                    ast.Alias(
                        alias="last_event",
                        expr=ast.Call(
                            name="argMax",
                            args=[
                                ast.Tuple(
                                    exprs=[
                                        ast.Field(chain=["uuid"]),
                                        ast.Field(chain=["timestamp"]),
                                        ast.Field(chain=["properties"]),
                                    ]
                                ),
                                ast.Field(chain=["timestamp"]),
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="last_event",
                        expr=ast.Call(
                            name="argMax",
                            args=[
                                ast.Field(chain=["last_event"]),
                                ast.Field(chain=["per_issue_per_revenue_entity", "last_seen"]),
                            ],
                        ),
                    ),
                ]
            )

        if self.sort_by_revenue:
            expr_pairs.append(
                [
                    ast.Alias(
                        alias="latest_revenue",
                        expr=ast.Call(
                            name="argMax",
                            args=[
                                ast.Field(chain=[self.revenue_entity, "revenue_analytics", "revenue"]),
                                ast.Field(chain=["timestamp"]),
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="revenue",
                        expr=ast.Call(
                            name="sum", args=[ast.Field(chain=["per_issue_per_revenue_entity", "latest_revenue"])]
                        ),
                    ),
                ]
            )

        expr_pairs.append(
            [
                ast.Alias(
                    alias="library",
                    expr=ast.Call(
                        name="argMax", args=[ast.Field(chain=["properties", "$lib"]), ast.Field(chain=["timestamp"])]
                    ),
                ),
                ast.Alias(
                    alias="library",
                    expr=ast.Call(
                        name="argMax",
                        args=[
                            ast.Field(chain=["library"]),
                            ast.Field(chain=["per_issue_per_revenue_entity", "last_seen"]),
                        ],
                    ),
                ),
            ]
        )

        return expr_pairs

    def select_sparkline_array(self, date_from: datetime.datetime, date_to: datetime.datetime, resolution: int):
        """
        This function partitions a given time range into segments (or "buckets") based on the specified resolution and then computes the number of events occurring in each segment.
        The resolution determines the total number of segments in the time range.
        Accordingly, the duration of each segment is dictated by the total time range and the resolution.

        The equivalent SQL would look like:
            WITH
                toDateTime('2025-03-01 00:00:00') AS date_from,
                toDateTime('2025-03-20 00:00:00') AS date_to,
                10 AS resolution,
            SELECT
                sumForEach(
                    arrayMap(
                        bin ->
                            IF(
                                timestamp > bin AND dateDiff('seconds', bin, timestamp) < dateDiff('seconds', date_from, date_to) / resolution,
                                1,
                                0
                            ), ## If we are inside the right bucket, return 1, otherwise 0
                        arrayMap(
                            i -> dateAdd(
                                start_time,
                                toIntervalSecond(i * dateDiff('seconds', date_from, date_to) / resolution)
                            ),
                            range(0, resolution)
                        ) ## Generate an array of len resolution containing the start times of each segment
                    )
                ) AS counts
        """
        start_time = ast.Call(
            name="toDateTime",
            args=[
                ast.Constant(value=date_from),
            ],
        )
        end_time = ast.Call(
            name="toDateTime",
            args=[
                ast.Constant(value=date_to),
            ],
        )
        total_size = ast.Call(
            name="dateDiff",
            args=[
                ast.Constant(value="seconds"),
                start_time,
                end_time,
            ],
        )
        bin_size = ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Div,
            left=total_size,
            right=ast.Constant(value=resolution),
        )
        bin_timestamps = ast.Call(
            name="arrayMap",
            args=[
                ast.Lambda(
                    args=["i"],
                    expr=ast.Call(
                        name="dateAdd",
                        args=[
                            start_time,
                            ast.Call(
                                name="toIntervalSecond",
                                args=[
                                    ast.ArithmeticOperation(
                                        op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["i"]), right=bin_size
                                    )
                                ],
                            ),
                        ],
                    ),
                ),
                ast.Call(
                    name="range",
                    args=[
                        ast.Constant(value=0),
                        ast.Constant(value=resolution),
                    ],
                ),
            ],
        )
        hot_indices = ast.Call(
            name="arrayMap",
            args=[
                ast.Lambda(
                    args=["bin"],
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Gt,
                                        left=ast.Field(chain=["timestamp"]),
                                        right=ast.Field(chain=["bin"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.LtEq,
                                        left=ast.Call(
                                            name="dateDiff",
                                            args=[
                                                ast.Constant(value="seconds"),
                                                ast.Field(chain=["bin"]),
                                                ast.Field(chain=["timestamp"]),
                                            ],
                                        ),
                                        right=bin_size,
                                    ),
                                ]
                            ),
                            ast.Constant(value=1),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                bin_timestamps,
            ],
        )
        summed = ast.Call(
            name="sumForEach",
            args=[hot_indices],
        )
        return summed

    @property
    def where(self):
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Call(
                name="isNotNull",
                args=[ast.Field(chain=["issue_id"])],
            ),
            ast.Placeholder(expr=ast.Field(chain=["filters"])),
        ]

        if self.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Call(
                        name="toDateTime",
                        args=[ast.Constant(value=self.date_from)],
                    ),
                )
            )

        if self.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Call(
                        name="toDateTime",
                        args=[ast.Constant(value=self.date_to)],
                    ),
                )
            )

        if self.query.issueId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["issue_id"]),
                    right=ast.Constant(value=self.query.issueId),
                )
            )

        if self.query.personId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["person_id"]),
                    right=ast.Constant(value=self.query.personId),
                )
            )

        if self.query.searchQuery:
            # TODO: Refine this so it only searches the frames inside $exception_list
            # TODO: We'd eventually need a more efficient searching strategy
            # TODO: Add fuzzy search support

            # first parse the search query to split it into words, except for quoted strings
            # then search for each word in the exception properties
            tokens = search_tokenizer(self.query.searchQuery)
            and_exprs: list[ast.Expr] = []

            if len(tokens) > 100:
                raise ValidationError("Too many search tokens")

            for token in tokens:
                if not token:
                    continue

                or_exprs: list[ast.Expr] = []

                props_to_search = {
                    ("properties",): [
                        "$exception_types",
                        "$exception_values",
                        "$exception_sources",
                        "$exception_functions",
                        "email",
                    ],
                    ("person", "properties"): [
                        "email",
                    ],
                }
                for chain_prefix, properties in props_to_search.items():
                    for prop in properties:
                        or_exprs.append(
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Call(
                                    name="position",
                                    args=[
                                        ast.Call(name="lower", args=[ast.Field(chain=[*chain_prefix, prop])]),
                                        ast.Call(name="lower", args=[ast.Constant(value=token)]),
                                    ],
                                ),
                                right=ast.Constant(value=0),
                            )
                        )

                and_exprs.append(ast.Or(exprs=or_exprs))

            exprs.append(ast.And(exprs=and_exprs))

        # We do this prefetching of a list of "valid" issue id's based on issue properties that aren't in
        # CH, so that when we run the aggregation and LIMIT, we can filter out the invalid issue id's
        # This is a hack - it'll break down if the list of valid issue id's is too long, but we do it for now
        prefetched_ids = self.prefetch_issue_ids()
        if prefetched_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["issue_id"]),
                    right=ast.Constant(value=prefetched_ids),
                )
            )

        return ast.And(exprs=exprs)

    def _calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                filters=HogQLFilters(
                    filterTestAccounts=self.query.filterTestAccounts,
                    properties=self.hogql_properties,
                ),
            )

        columns: list[str] = query_result.columns or []
        results = self.results(columns, query_result.results)

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def results(self, columns: list[str], query_results: list):
        results = []
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        issue_ids = [result["id"] for result in mapped_results]

        with self.timings.measure("issue_fetching_execute"):
            issues = self.error_tracking_issues(issue_ids)

        with self.timings.measure("issue_resolution"):
            for result_dict in mapped_results:
                issue = issues.get(str(result_dict["id"]))

                if issue:
                    results.append(
                        issue
                        | {
                            "last_seen": result_dict.get("last_seen"),
                            "library": result_dict.get("library"),
                            "first_event": (
                                self.extract_event(result_dict.get("first_event"))
                                if self.query.withFirstEvent
                                else None
                            ),
                            "last_event": (
                                self.extract_event(result_dict.get("last_event")) if self.query.withLastEvent else None
                            ),
                            "aggregations": (
                                self.extract_aggregations(result_dict) if self.query.withAggregations else None
                            ),
                            "revenue": (result_dict.get("revenue") if self.sort_by_revenue else None),
                        }
                    )

        return results

    def extract_event(self, event_tuple):
        if event_tuple is None:
            return None
        else:
            return {
                "uuid": str(event_tuple[0]),
                "timestamp": str(event_tuple[1]),
                "properties": event_tuple[2],
            }

    def get_volume_buckets(self) -> list[datetime.datetime]:
        if self.query.volumeResolution == 0:
            return []
        total_ms = (self.date_to - self.date_from).total_seconds() * 1000
        bin_size = int(total_ms / self.query.volumeResolution)
        return [
            self.date_from + datetime.timedelta(milliseconds=i * bin_size) for i in range(self.query.volumeResolution)
        ]

    def extract_aggregations(self, result):
        # TODO: Remove unused volumeRange. (keeping it for now because of cached values)
        aggregations = {f: result[f] for f in ("occurrences", "sessions", "users", "volumeRange")}
        histogram_bins = self.get_volume_buckets()
        aggregations["volume_buckets"] = [
            {"label": bin.isoformat(), "value": aggregations["volumeRange"][i] if aggregations["volumeRange"] else None}
            for i, bin in enumerate(histogram_bins)
        ]
        return aggregations

    @property
    def order_direction(self):
        if self.sort_by_revenue:
            return "DESC"

        if self.query.orderDirection:
            return self.query.orderDirection.value

        return "ASC" if self.query.orderBy == "first_seen" else "DESC"

    @property
    def sort_by_revenue(self):
        return self.query.orderBy == "revenue"

    def error_tracking_issues(self, ids):
        status = self.query.status
        queryset = (
            ErrorTrackingIssue.objects.with_first_seen()
            .select_related("assignment")
            .prefetch_related("external_issues__integration")
            .filter(team=self.team, id__in=ids)
        )

        if self.query.issueId:
            queryset = queryset.filter(id=self.query.issueId)
        elif status and not status == "all":
            queryset = queryset.filter(status=status)

        if self.query.assignee:
            queryset = (
                queryset.filter(assignment__user_id=self.query.assignee.id)
                if self.query.assignee.type == "user"
                else queryset.filter(assignment__role_id=self.query.assignee.id)
            )

        for filter in self.issue_properties:
            queryset = property_to_django_filter(queryset, filter)

        serializer = ErrorTrackingIssueSerializer(queryset, many=True)
        return {issue["id"]: issue for issue in serializer.data}

    def prefetch_issue_ids(self) -> list[str]:
        # We hit postgres to get a list of "valid" issue id's based on issue properties that aren't in
        # CH, but that we want to filter the returned results by. This is a hack - it'll break down if
        # the list of valid issue id's is too long, but we do it for now, until we can get issue properties
        # into CH

        use_prefetched = False
        if self.query.issueId:
            # If we have an issueId, we should just use that
            return [self.query.issueId]

        queryset = ErrorTrackingIssue.objects.with_first_seen().select_related("assignment").filter(team=self.team)

        if self.query.status and self.query.status not in ["all", "active"]:
            use_prefetched = True
            queryset = queryset.filter(status=self.query.status)

        if self.query.assignee:
            use_prefetched = True
            queryset = (
                queryset.filter(assignment__user_id=self.query.assignee.id)
                if self.query.assignee.type == "user"
                else queryset.filter(assignment__role_id=str(self.query.assignee.id))
            )

        for filter in self.issue_properties:
            queryset = property_to_django_filter(queryset, filter)

        if not use_prefetched:
            return []

        return [str(issue["id"]) for issue in queryset.values("id")]

    @cached_property
    def issue_properties(self):
        return [value for value in self.properties if "error_tracking_issue" == value.type]

    @cached_property
    def hogql_properties(self):
        return [value for value in self.properties if "error_tracking_issue" != value.type]

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []

    @cached_property
    def revenue_entity_field(self):
        key = "id" if (self.revenue_entity == "person" or self.revenue_entity is None) else "key"
        return ast.Field(chain=["e", self.revenue_entity, key])

    @cached_property
    def revenue_entity(self):
        return self.query.revenueEntity or RevenueEntity.PERSON


def search_tokenizer(query: str) -> list[str]:
    # parse the search query to split it into words, except for quoted strings. Strip quotes from quoted strings.
    # Example: 'This is a "quoted string" and this is \'another one\' with some words'
    # Output: ['This', 'is', 'a', 'quoted string', 'and', 'this', 'is', 'another one', 'with', 'some', 'words']
    # This doesn't handle nested quotes, and some complex edge cases, but we don't really need that for now.
    # If requirements do change, consider using a proper parser like `pyparsing`
    pattern = r'"[^"]*"|\'[^\']*\'|\S+'
    tokens = re.findall(pattern, query)
    return [token.strip("'\"") for token in tokens]
