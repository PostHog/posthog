import datetime
from typing import cast

from posthog.schema import ErrorTrackingIssueFilter, ErrorTrackingQuery, HogQLFilters, PropertyGroupFilterValue

from posthog.hogql import ast

from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property.util import property_to_django_filter

from products.error_tracking.backend.api.issues import ErrorTrackingIssuePreviewSerializer
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import (
    build_event_where_exprs,
    build_select_expressions,
    extract_aggregations,
    extract_event,
    order_direction,
)
from products.error_tracking.backend.models import ErrorTrackingIssue


class ErrorTrackingQueryV1Builder:
    def __init__(self, query: ErrorTrackingQuery, team, date_from: datetime.datetime, date_to: datetime.datetime):
        self.query = query
        self.team = team
        self.date_from = date_from
        self.date_to = date_to

    def build_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=build_select_expressions(self.query, self.date_from, self.date_to),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=self._where,
            group_by=[ast.Field(chain=["id"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=[self.query.orderBy]), order=order_direction(self.query))],
        )

    def hogql_filters(self) -> HogQLFilters:
        return HogQLFilters(
            filterTestAccounts=self.query.filterTestAccounts,
            properties=cast(list, self._hogql_properties),
        )

    def process_results(self, columns: list[str], rows: list) -> list:
        mapped = [dict(zip(columns, row)) for row in rows]
        issues = self._fetch_issues([r["id"] for r in mapped])

        results = []
        for row in mapped:
            issue = issues.get(str(row["id"]))
            if issue:
                results.append(
                    issue
                    | {
                        "last_seen": row.get("last_seen"),
                        "library": row.get("library"),
                        "function": row.get("function"),
                        "source": row.get("source"),
                        "first_event": extract_event(row.get("first_event")) if self.query.withFirstEvent else None,
                        "last_event": extract_event(row.get("last_event")) if self.query.withLastEvent else None,
                        "aggregations": extract_aggregations(
                            row, self.date_from, self.date_to, self.query.volumeResolution
                        )
                        if self.query.withAggregations
                        else None,
                    }
                )
        return results

    @property
    def _where(self) -> ast.And:
        exprs = build_event_where_exprs(self.query, self.date_from, self.date_to)

        # Prefetch issue IDs from Postgres to filter results by properties not available in CH.
        # This is a stopgap — breaks at scale if the list grows too large.
        prefetched_ids = self._prefetch_issue_ids()
        if prefetched_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["e", "issue_id"]),
                    right=ast.Constant(value=prefetched_ids),
                )
            )

        return ast.And(exprs=exprs)

    def _fetch_issues(self, ids: list) -> dict:
        status = self.query.status
        queryset = (
            ErrorTrackingIssue.objects.with_first_seen().select_related("assignment").filter(team=self.team, id__in=ids)  # pyright: ignore[reportAttributeAccessIssue]
        )

        if self.query.issueId:
            queryset = queryset.filter(id=self.query.issueId)
        elif status and status != "all":
            queryset = queryset.filter(status=status)

        if self.query.assignee:
            queryset = (
                queryset.filter(assignment__user_id=self.query.assignee.id)
                if self.query.assignee.type == "user"
                else queryset.filter(assignment__role_id=self.query.assignee.id)
            )

        for f in self._issue_properties:
            queryset = property_to_django_filter(queryset, f)

        serializer = ErrorTrackingIssuePreviewSerializer(queryset, many=True)
        return {issue["id"]: issue for issue in serializer.data}

    def _prefetch_issue_ids(self) -> list[str]:
        if self.query.issueId:
            return [self.query.issueId]

        use_prefetched = False
        queryset = ErrorTrackingIssue.objects.with_first_seen().select_related("assignment").filter(team=self.team)  # pyright: ignore[reportAttributeAccessIssue]

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

        for f in self._issue_properties:
            queryset = property_to_django_filter(queryset, f)

        return [str(issue["id"]) for issue in queryset.values("id")] if use_prefetched else []

    @cached_property
    def _properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []

    @cached_property
    def _issue_properties(self):
        return [v for v in self._properties if isinstance(v, ErrorTrackingIssueFilter)]

    @cached_property
    def _hogql_properties(self):
        return [v for v in self._properties if not isinstance(v, (ErrorTrackingIssueFilter, PropertyGroupFilterValue))]
