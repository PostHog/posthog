import datetime
from typing import cast

from posthog.schema import (
    ErrorTrackingIssueFilter,
    ErrorTrackingQuery,
    HogQLFilters,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast

from posthog.models.filters.mixins.utils import cached_property

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import (
    build_event_where_exprs,
    build_select_expressions,
    extract_aggregations,
    extract_event,
    order_direction,
)


class ErrorTrackingQueryV2Builder:
    def __init__(self, query: ErrorTrackingQuery, date_from: datetime.datetime, date_to: datetime.datetime):
        self.query = query
        self.date_from = date_from
        self.date_to = date_to

    def build_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self._outer_select_expressions(),
            select_from=ast.JoinExpr(
                table=self._inner_subquery(),
                alias="agg",
                next_join=ast.JoinExpr(
                    join_type="INNER JOIN",
                    table=ast.Field(chain=["system", "error_tracking_issues"]),
                    alias="issues",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["agg", "id"]),
                            right=ast.Field(chain=["issues", "id"]),
                        ),
                    ),
                    next_join=ast.JoinExpr(
                        join_type="LEFT JOIN",
                        table=self._fingerprints_subquery(),
                        alias="fp",
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["fp", "issue_id"]),
                                right=ast.Field(chain=["issues", "id"]),
                            ),
                        ),
                        next_join=ast.JoinExpr(
                            join_type="LEFT JOIN",
                            table=ast.Field(chain=["system", "error_tracking_issue_assignments"]),
                            alias="assignment",
                            constraint=ast.JoinConstraint(
                                constraint_type="ON",
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["assignment", "issue_id"]),
                                    right=ast.Field(chain=["issues", "id"]),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            where=self._outer_where,
            order_by=[ast.OrderExpr(expr=ast.Field(chain=[self.query.orderBy]), order=order_direction(self.query))],
        )

    def hogql_filters(self) -> HogQLFilters:
        return HogQLFilters(
            filterTestAccounts=self.query.filterTestAccounts,
            properties=cast(list, self._hogql_properties),
        )

    def process_results(self, columns: list[str], rows: list) -> list:
        results = []
        for row in rows:
            result_dict = dict(zip(columns, row))
            results.append(
                {
                    "id": str(result_dict["id"]),
                    "status": result_dict.get("status"),
                    "name": result_dict.get("name"),
                    "description": result_dict.get("description"),
                    "first_seen": result_dict.get("first_seen"),
                    "assignee": self._extract_assignee(result_dict),
                    "last_seen": result_dict.get("last_seen"),
                    "library": result_dict.get("library"),
                    "function": result_dict.get("function"),
                    "source": result_dict.get("source"),
                    "first_event": extract_event(result_dict.get("first_event")) if self.query.withFirstEvent else None,
                    "last_event": extract_event(result_dict.get("last_event")) if self.query.withLastEvent else None,
                    "aggregations": extract_aggregations(
                        result_dict, self.date_from, self.date_to, self.query.volumeResolution
                    )
                    if self.query.withAggregations
                    else None,
                }
            )
        return results

    def _inner_subquery(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=build_select_expressions(self.query, self.date_from, self.date_to),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=ast.And(exprs=build_event_where_exprs(self.query, self.date_from, self.date_to)),
            group_by=[ast.Field(chain=["id"])],
        )

    def _fingerprints_subquery(self) -> ast.SelectQuery:
        """Historical first_seen per issue, regardless of the queried date range."""
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["issue_id"]),
                ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["first_seen"])])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["system", "error_tracking_issue_fingerprints"])),
            group_by=[ast.Field(chain=["issue_id"])],
        )

    def _outer_select_expressions(self) -> list[ast.Expr]:
        def from_agg(field: str) -> ast.Field:
            return ast.Field(chain=["agg", field])

        exprs: list[ast.Expr] = [
            ast.Alias(alias="id", expr=from_agg("id")),
            ast.Alias(alias="status", expr=ast.Field(chain=["issues", "status"])),
            ast.Alias(alias="name", expr=ast.Field(chain=["issues", "name"])),
            ast.Alias(alias="description", expr=ast.Field(chain=["issues", "description"])),
            ast.Alias(alias="last_seen", expr=from_agg("last_seen")),
            ast.Alias(alias="first_seen", expr=ast.Field(chain=["fp", "first_seen"])),
            ast.Alias(alias="assignee_user_id", expr=ast.Field(chain=["assignment", "user_id"])),
            ast.Alias(alias="assignee_role_id", expr=ast.Field(chain=["assignment", "role_id"])),
            ast.Alias(alias="function", expr=from_agg("function")),
            ast.Alias(alias="source", expr=from_agg("source")),
        ]

        if self.query.withAggregations:
            exprs.extend(
                [
                    ast.Alias(alias="occurrences", expr=from_agg("occurrences")),
                    ast.Alias(alias="sessions", expr=from_agg("sessions")),
                    ast.Alias(alias="users", expr=from_agg("users")),
                    ast.Alias(alias="volumeRange", expr=from_agg("volumeRange")),
                ]
            )

        if self.query.withFirstEvent:
            exprs.append(ast.Alias(alias="first_event", expr=from_agg("first_event")))

        if self.query.withLastEvent:
            exprs.append(ast.Alias(alias="last_event", expr=from_agg("last_event")))

        exprs.append(ast.Alias(alias="library", expr=from_agg("library")))

        return exprs

    @property
    def _outer_where(self) -> ast.And | None:
        """Filters on postgres-joined tables. Event-level filters live in the inner subquery."""
        exprs: list[ast.Expr] = []

        if self.query.status and self.query.status != "all":
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["issues", "status"]),
                    right=ast.Constant(value=self.query.status),
                )
            )

        if self.query.assignee:
            if self.query.assignee.type == "user":
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["assignment", "user_id"]),
                        right=ast.Constant(value=self.query.assignee.id),
                    )
                )
            else:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["assignment", "role_id"]),
                        right=ast.Constant(value=str(self.query.assignee.id)),
                    )
                )

        for prop in self._issue_properties:
            expr = self._issue_property_to_ast(prop)
            if expr is not None:
                exprs.append(expr)

        return ast.And(exprs=exprs) if exprs else None

    def _extract_assignee(self, row: dict) -> dict | None:
        user_id = row.get("assignee_user_id")
        role_id = row.get("assignee_role_id")
        if user_id:
            return {"id": user_id, "type": "user"}
        if role_id:
            return {"id": str(role_id), "type": "role"}
        return None

    @cached_property
    def _properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []

    @cached_property
    def _issue_properties(self) -> list[ErrorTrackingIssueFilter]:
        return [v for v in self._properties if isinstance(v, ErrorTrackingIssueFilter)]

    @cached_property
    def _hogql_properties(self):
        return [v for v in self._properties if not isinstance(v, (ErrorTrackingIssueFilter, PropertyGroupFilterValue))]

    def _issue_property_to_ast(self, prop: ErrorTrackingIssueFilter) -> ast.Expr | None:
        key = "description" if prop.key == "issue_description" else prop.key

        field_chain_map: dict[str, list[str | int]] = {
            "name": ["issues", "name"],
            "description": ["issues", "description"],
            "status": ["issues", "status"],
            "first_seen": ["fp", "first_seen"],
        }

        field_chain = field_chain_map.get(key)
        if field_chain is None:
            return None

        field = ast.Field(chain=field_chain)
        value = prop.value
        operator = prop.operator

        def make_value(v) -> ast.Expr:
            if key == "first_seen":
                return ast.Call(name="toDateTime", args=[ast.Constant(value=str(v))])
            return ast.Constant(value=v)

        if operator == PropertyOperator.EXACT:
            raw = value if isinstance(value, list) else [value]
            values: list[str | float | bool] = [v for v in raw if v is not None]
            if not values:
                return None
            if len(values) == 1:
                return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=field, right=make_value(values[0]))
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=field,
                right=ast.Tuple(exprs=[make_value(v) for v in values]),
            )

        if operator == PropertyOperator.IS_NOT:
            raw = value if isinstance(value, list) else [value]
            values: list[str | float | bool] = [v for v in raw if v is not None]
            if not values:
                return None
            if len(values) == 1:
                return ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=field, right=make_value(values[0]))
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotIn,
                left=field,
                right=ast.Tuple(exprs=[make_value(v) for v in values]),
            )

        if operator == PropertyOperator.ICONTAINS:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.ILike, left=field, right=ast.Constant(value=f"%{value}%")
            )

        if operator == PropertyOperator.NOT_ICONTAINS:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotILike, left=field, right=ast.Constant(value=f"%{value}%")
            )

        if operator in (PropertyOperator.GT, PropertyOperator.IS_DATE_AFTER):
            return ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=field, right=make_value(value))

        if operator == PropertyOperator.GTE:
            return ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=field, right=make_value(value))

        if operator in (PropertyOperator.LT, PropertyOperator.IS_DATE_BEFORE):
            return ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=field, right=make_value(value))

        if operator == PropertyOperator.LTE:
            return ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=field, right=make_value(value))

        if operator == PropertyOperator.IS_SET:
            return ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=field, right=ast.Constant(value=None))

        if operator == PropertyOperator.IS_NOT_SET:
            return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=field, right=ast.Constant(value=None))

        return None
