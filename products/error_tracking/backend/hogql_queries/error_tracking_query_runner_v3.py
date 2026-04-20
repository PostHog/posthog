import datetime
from typing import cast

from django.core.exceptions import ValidationError

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
    extract_aggregations,
    extract_event,
    innermost_frame_attribute,
    order_direction,
    search_tokenizer,
    select_sparkline_array,
)


class ErrorTrackingQueryV3Builder:
    """ClickHouse-only query builder using the denormalized fingerprint table.

    Uses the HogQL virtual fields on events (issue_id_v2, issue_name,
    issue_status, etc.) which trigger a LazyJoin to the denormalized table.
    This avoids Postgres and the old overrides table entirely.
    """

    def __init__(self, query: ErrorTrackingQuery, date_from: datetime.datetime, date_to: datetime.datetime):
        self.query = query
        self.date_from = date_from
        self.date_to = date_to

    def build_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self._select_expressions(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=ast.And(exprs=self._where_exprs()),
            group_by=[ast.Field(chain=["id"])],
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

    def _select_expressions(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = [
            # issue_id from the denormalized fingerprint_issue_state table
            ast.Alias(alias="id", expr=ast.Field(chain=["e", "issue_id_v2"])),
            # metadata from denormalized table via HogQL virtual fields
            ast.Alias(alias="status", expr=ast.Call(name="any", args=[ast.Field(chain=["e", "issue_status"])])),
            ast.Alias(alias="name", expr=ast.Call(name="any", args=[ast.Field(chain=["e", "issue_name"])])),
            ast.Alias(
                alias="description", expr=ast.Call(name="any", args=[ast.Field(chain=["e", "issue_description"])])
            ),
            ast.Alias(
                alias="assignee_user_id",
                expr=ast.Call(name="any", args=[ast.Field(chain=["e", "issue_assigned_user_id"])]),
            ),
            ast.Alias(
                alias="assignee_role_id",
                expr=ast.Call(name="any", args=[ast.Field(chain=["e", "issue_assigned_role_id"])]),
            ),
            # timestamps
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["e", "timestamp"])])),
            ast.Alias(
                alias="first_seen",
                expr=ast.Call(name="min", args=[ast.Field(chain=["e", "issue_first_seen"])]),
            ),
            # frame info from events
            ast.Alias(alias="function", expr=innermost_frame_attribute("$exception_functions")),
            ast.Alias(alias="source", expr=innermost_frame_attribute("$exception_sources")),
        ]

        if self.query.withAggregations:
            exprs.extend(
                [
                    ast.Alias(
                        alias="occurrences",
                        expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["e", "uuid"])]),
                    ),
                    ast.Alias(
                        alias="sessions",
                        expr=ast.Call(
                            name="count",
                            distinct=True,
                            args=[
                                ast.Call(
                                    name="nullIf",
                                    args=[ast.Field(chain=["e", "$session_id"]), ast.Constant(value="")],
                                )
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="users",
                        expr=ast.Call(
                            name="count",
                            distinct=True,
                            args=[
                                ast.Call(
                                    name="coalesce",
                                    args=[
                                        ast.Call(
                                            name="nullIf",
                                            args=[
                                                ast.Call(name="toString", args=[ast.Field(chain=["e", "person_id"])]),
                                                ast.Constant(value="00000000-0000-0000-0000-000000000000"),
                                            ],
                                        ),
                                        ast.Field(chain=["e", "distinct_id"]),
                                    ],
                                )
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="volumeRange",
                        expr=select_sparkline_array(self.date_from, self.date_to, self.query.volumeResolution),
                    ),
                ]
            )

        if self.query.withFirstEvent:
            exprs.append(
                ast.Alias(
                    alias="first_event",
                    expr=ast.Call(
                        name="argMin",
                        args=[
                            ast.Tuple(
                                exprs=[
                                    ast.Field(chain=["e", "uuid"]),
                                    ast.Field(chain=["e", "distinct_id"]),
                                    ast.Field(chain=["e", "timestamp"]),
                                    ast.Field(chain=["e", "properties"]),
                                ]
                            ),
                            ast.Field(chain=["e", "timestamp"]),
                        ],
                    ),
                )
            )

        if self.query.withLastEvent:
            exprs.append(
                ast.Alias(
                    alias="last_event",
                    expr=ast.Call(
                        name="argMax",
                        args=[
                            ast.Tuple(
                                exprs=[
                                    ast.Field(chain=["e", "uuid"]),
                                    ast.Field(chain=["e", "distinct_id"]),
                                    ast.Field(chain=["e", "timestamp"]),
                                    ast.Field(chain=["e", "properties"]),
                                ]
                            ),
                            ast.Field(chain=["e", "timestamp"]),
                        ],
                    ),
                )
            )

        exprs.append(
            ast.Alias(
                alias="library",
                expr=ast.Call(
                    name="argMax",
                    args=[ast.Field(chain=["e", "properties", "$lib"]), ast.Field(chain=["e", "timestamp"])],
                ),
            )
        )

        return exprs

    def _where_exprs(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["e", "event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Call(name="isNotNull", args=[ast.Field(chain=["e", "issue_id_v2"])]),
            ast.Placeholder(expr=ast.Field(chain=["filters"])),
        ]

        if self.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["e", "timestamp"]),
                    right=ast.Call(name="toDateTime", args=[ast.Constant(value=self.date_from)]),
                )
            )

        if self.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["e", "timestamp"]),
                    right=ast.Call(name="toDateTime", args=[ast.Constant(value=self.date_to)]),
                )
            )

        if self.query.issueId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["e", "issue_id_v2"]),
                    right=ast.Constant(value=self.query.issueId),
                )
            )

        if self.query.personId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["e", "person_id"]),
                    right=ast.Constant(value=self.query.personId),
                )
            )

        if self.query.groupKey and self.query.groupTypeIndex is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["e", f"$group_{self.query.groupTypeIndex}"]),
                    right=ast.Constant(value=self.query.groupKey),
                )
            )

        if self.query.searchQuery:
            tokens = search_tokenizer(self.query.searchQuery)
            if len(tokens) > 100:
                raise ValidationError("Too many search tokens")

            and_exprs: list[ast.Expr] = []
            for token in tokens:
                if not token:
                    continue
                or_exprs: list[ast.Expr] = []
                props_to_search = {
                    ("e", "properties"): [
                        "$exception_types",
                        "$exception_values",
                        "$exception_sources",
                        "$exception_functions",
                        "email",
                    ],
                    ("e", "person", "properties"): ["email"],
                }
                for chain_prefix, properties in props_to_search.items():
                    for property_name in properties:
                        or_exprs.append(
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Call(
                                    name="position",
                                    args=[
                                        ast.Call(name="lower", args=[ast.Field(chain=[*chain_prefix, property_name])]),
                                        ast.Call(name="lower", args=[ast.Constant(value=token)]),
                                    ],
                                ),
                                right=ast.Constant(value=0),
                            )
                        )
                and_exprs.append(ast.Or(exprs=or_exprs))

            exprs.append(ast.And(exprs=and_exprs))

        # issue-level filters
        if self.query.status and self.query.status != "all":
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["e", "issue_status"]),
                    right=ast.Constant(value=self.query.status),
                )
            )

        if self.query.assignee:
            if self.query.assignee.type == "user":
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["e", "issue_assigned_user_id"]),
                        right=ast.Constant(value=self.query.assignee.id),
                    )
                )
            else:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["e", "issue_assigned_role_id"]),
                        right=ast.Constant(value=str(self.query.assignee.id)),
                    )
                )

        for prop in self._issue_properties:
            expr = self._issue_property_to_ast(prop)
            if expr is not None:
                exprs.append(expr)

        return exprs

    def _extract_assignee(self, row: dict) -> dict | None:
        user_id = row.get("assignee_user_id")
        role_id = row.get("assignee_role_id")
        if user_id:
            return {"id": int(user_id), "type": "user"}
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
        return [v for v in self._properties if not isinstance(v, ErrorTrackingIssueFilter | PropertyGroupFilterValue)]

    def _issue_property_to_ast(self, prop: ErrorTrackingIssueFilter) -> ast.Expr | None:
        key = "description" if prop.key == "issue_description" else prop.key

        field_chain_map: dict[str, list[str | int]] = {
            "name": ["e", "issue_name"],
            "description": ["e", "issue_description"],
            "status": ["e", "issue_status"],
            "first_seen": ["e", "issue_first_seen"],
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

        def normalize_values(raw_value: object | list[object]) -> list[str | float | bool]:
            candidates = raw_value if isinstance(raw_value, list) else [raw_value]
            return [candidate for candidate in candidates if isinstance(candidate, (str, float, bool))]

        if operator == PropertyOperator.EXACT:
            values = normalize_values(value)
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
            not_values = normalize_values(value)
            if not not_values:
                return None
            if len(not_values) == 1:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq, left=field, right=make_value(not_values[0])
                )
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotIn,
                left=field,
                right=ast.Tuple(exprs=[make_value(v) for v in not_values]),
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
