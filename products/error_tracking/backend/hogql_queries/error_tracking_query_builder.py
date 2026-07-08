import datetime
from typing import Any, cast

from django.core.exceptions import ValidationError

from posthog.schema import (
    ErrorTrackingIssueFilter,
    ErrorTrackingQuery,
    FilterLogicalOperator,
    HogQLFilters,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.models.team.team import Team

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import (
    extract_aggregations,
    extract_event,
    innermost_frame_attribute,
    order_direction,
    search_tokenizer,
    select_sparkline_array,
)


def _bin_idx_expr(date_from: datetime.datetime, date_to: datetime.datetime, resolution: int) -> ast.Call:
    start = ast.Call(name="toDateTime", args=[ast.Constant(value=date_from)])
    end = ast.Call(name="toDateTime", args=[ast.Constant(value=date_to)])
    elapsed = ast.Call(name="dateDiff", args=[ast.Constant(value="seconds"), start, ast.Field(chain=["timestamp"])])
    total = ast.Call(name="dateDiff", args=[ast.Constant(value="seconds"), start, end])
    # `greatest(1, ...)` guards against sub-`resolution`-second windows where
    # `intDiv(total, resolution)` would be 0 and crash the inner intDiv.
    bin_size = ast.Call(
        name="greatest",
        args=[ast.Constant(value=1), ast.Call(name="intDiv", args=[total, ast.Constant(value=resolution)])],
    )
    raw = ast.Call(name="intDiv", args=[elapsed, bin_size])
    return ast.Call(name="least", args=[ast.Constant(value=resolution - 1), raw])


def _volume_range_expr(resolution: int) -> ast.Call:
    return ast.Call(
        name="sumForEach",
        args=[
            ast.Call(
                name="arrayMap",
                args=[
                    ast.Lambda(
                        args=["i"],
                        expr=ast.Call(
                            name="if",
                            args=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["ev", "bin_idx"]),
                                    right=ast.Field(chain=["i"]),
                                ),
                                ast.Field(chain=["ev", "occ"]),
                                ast.Call(name="_toUInt64", args=[ast.Constant(value=0)]),
                            ],
                        ),
                    ),
                    ast.Call(name="range", args=[ast.Constant(value=0), ast.Constant(value=resolution)]),
                ],
            )
        ],
    )


# Aggregator name → corresponding -State / -Merge combinator name.
# We only need to know the base names we actually use in V3.
_STATE_SUFFIX = "State"
_MERGE_SUFFIX = "Merge"


def _state(call: ast.Call) -> ast.Call:
    """Wrap a regular aggregator call in its `-State` variant (e.g. `count()` → `countState()`)."""
    return ast.Call(name=call.name + _STATE_SUFFIX, args=call.args, distinct=call.distinct)


def _merge(state_alias: str, base_aggregator: str) -> ast.Call:
    """Build the `-Merge` call that finalizes a `-State` column from the inner subquery."""
    return ast.Call(name=base_aggregator + _MERGE_SUFFIX, args=[ast.Field(chain=["ev", state_alias])])


class ErrorTrackingQueryBuilder:
    """ClickHouse-only query builder using the denormalized fingerprint table.

    Two query shapes are supported:

    * **Optimized two-pass shape (default).** Pre-aggregates events by
      `cityHash64($exception_fingerprint)` (`fp_hash`) using `-State`
      combinators in an inner subquery, bucketing by `bin_idx` so the outer
      query can assemble `volumeRange` cheaply, then INNER JOINs to
      `error_tracking_fingerprint_issue_state` and finalises with
      `-Merge` aggregators in the outer `GROUP BY issue_id`.

    * **Legacy single-query shape.** Retained for the edge case where a
      user-supplied `filterGroup` contains issue-level filters inside an OR
      group with event-level filters — the two-pass split cannot express
      mixed-OR semantics across the events/issue boundary.
    """

    def __init__(self, query: ErrorTrackingQuery, team: Team, date_from: datetime.datetime, date_to: datetime.datetime):
        self.query = query
        self.team = team
        self.date_from = date_from
        self.date_to = date_to

    def build_query(self) -> ast.SelectQuery:
        if self._needs_legacy_shape():
            return self._build_query_legacy()
        return self._build_query_optimized()

    def hogql_filters(self) -> HogQLFilters:
        # User-supplied properties are handled directly in the per-shape
        # `_where_exprs` methods so the OR/AND operator on
        # `filterGroup.values[0]` is respected. The `{filters}` placeholder is
        # left in place to apply `filterTestAccounts` only.
        return HogQLFilters(
            filterTestAccounts=self.query.filterTestAccounts,
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

    # ---------------------------------------------------------------------
    # Shape dispatch
    # ---------------------------------------------------------------------

    def _needs_legacy_shape(self) -> bool:
        """Return True if the user-supplied filterGroup contains issue-level
        filters that cannot be cleanly routed to the outer query.

        The two-pass shape can only split filters cleanly when all
        issue-level leaves are AND-combined with the rest of the tree. If an
        `ErrorTrackingIssueFilter` appears anywhere in the tree we fall back
        to the legacy shape rather than risk producing wrong results for
        mixed-OR groups.
        """
        if not self.query.filterGroup or not self.query.filterGroup.values:
            return False
        return self._tree_contains_issue_filter(self.query.filterGroup.values[0])

    def _tree_contains_issue_filter(self, node: object) -> bool:
        if isinstance(node, ErrorTrackingIssueFilter):
            return True
        if isinstance(node, PropertyGroupFilterValue):
            return any(self._tree_contains_issue_filter(child) for child in node.values)
        return False

    # ---------------------------------------------------------------------
    # Optimized two-pass shape
    # ---------------------------------------------------------------------

    def _build_query_optimized(self) -> ast.SelectQuery:
        inner = self._build_inner_query()
        outer_where_exprs = self._outer_where_exprs()
        return ast.SelectQuery(
            select=self._outer_select_expressions(),
            select_from=ast.JoinExpr(
                table=inner,
                alias="ev",
                next_join=ast.JoinExpr(
                    table=ast.Field(chain=["posthog", "error_tracking_fingerprint_issue_state"]),
                    alias="fp_state",
                    join_type="INNER JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["ev", "fp_hash"]),
                            right=ast.Field(chain=["fp_state", "fp_hash"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            where=ast.And(exprs=outer_where_exprs) if outer_where_exprs else None,
            group_by=[ast.Field(chain=["id"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=[self.query.orderBy]), order=order_direction(self.query))],
        )

    def _build_inner_query(self) -> ast.SelectQuery:
        # Bucketing by bin_idx here lets the outer query assemble volumeRange
        # from the small post-aggregation set instead of per-event arrayMap.
        group_by: list[ast.Expr] = [ast.Field(chain=["fp_hash"])]
        if self.query.withAggregations:
            group_by.append(ast.Field(chain=["bin_idx"]))
        return ast.SelectQuery(
            select=self._inner_select_expressions(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=ast.And(exprs=self._inner_where_exprs()),
            group_by=group_by,
        )

    def _inner_select_expressions(self) -> list[ast.Expr]:
        # fp_hash is both the inner GROUP BY key and the JOIN key to fp_state.
        exprs: list[ast.Expr] = [
            ast.Alias(
                alias="fp_hash",
                expr=ast.Call(
                    name="cityHash64",
                    args=[ast.Field(chain=["e", "properties", "$exception_fingerprint"])],
                ),
            ),
            ast.Alias(alias="last_seen_fp", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="function_state", expr=_state(innermost_frame_attribute("$exception_functions"))),
            ast.Alias(alias="source_state", expr=_state(innermost_frame_attribute("$exception_sources"))),
            ast.Alias(
                alias="library_state",
                expr=_state(
                    ast.Call(
                        name="argMax",
                        args=[ast.Field(chain=["properties", "$lib"]), ast.Field(chain=["timestamp"])],
                    )
                ),
            ),
        ]

        if self.query.withAggregations:
            exprs.append(
                ast.Alias(
                    alias="bin_idx",
                    expr=_bin_idx_expr(self.date_from, self.date_to, self.query.volumeResolution),
                )
            )
            # `count(DISTINCT uuid)` is equivalent to `count()` because uuid is
            # the events primary key, but pays for a distinct hashset per group.
            exprs.append(ast.Alias(alias="occ", expr=ast.Call(name="count", args=[])))
            # `uniq()` is HLL-based and ~1-2% off vs exact `count(DISTINCT)`
            # on high-cardinality session ids, but much cheaper.
            exprs.append(
                ast.Alias(
                    alias="sessions_state",
                    expr=_state(
                        ast.Call(
                            name="uniq",
                            args=[
                                ast.Call(
                                    name="nullIf",
                                    args=[ast.Field(chain=["e", "$session_id"]), ast.Constant(value="")],
                                )
                            ],
                        )
                    ),
                )
            )
            # Same HLL tradeoff as `sessions`. Input semantics preserved
            # (resolved person_id with distinct_id fallback) so the user
            # population is unchanged — only the counting algorithm changed.
            exprs.append(
                ast.Alias(
                    alias="users_state",
                    expr=_state(
                        ast.Call(
                            name="uniq",
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
                        )
                    ),
                )
            )

        # Only the uuid is aggregated here; the runner fetches the selected events' properties
        # in a second point lookup. Aggregating the tuple directly would decompress every
        # matching event's properties blob just to keep one row per fingerprint.
        if self.query.withFirstEvent:
            exprs.append(
                ast.Alias(
                    alias="first_event_uuid_state",
                    expr=_state(
                        ast.Call(
                            name="argMin",
                            args=[ast.Field(chain=["e", "uuid"]), ast.Field(chain=["e", "timestamp"])],
                        )
                    ),
                )
            )

        if self.query.withLastEvent:
            exprs.append(
                ast.Alias(
                    alias="last_event_uuid_state",
                    expr=_state(
                        ast.Call(
                            name="argMax",
                            args=[ast.Field(chain=["e", "uuid"]), ast.Field(chain=["e", "timestamp"])],
                        )
                    ),
                )
            )

        return exprs

    def _inner_where_exprs(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["e", "event"]),
                right=ast.Constant(value="$exception"),
            ),
            # Drop events without a fingerprint up-front — they can never
            # satisfy the outer INNER JOIN anyway, so prune them here to
            # avoid a tiny null-fingerprint group in the inner hashmap.
            ast.Call(name="isNotNull", args=[ast.Field(chain=["e", "properties", "$exception_fingerprint"])]),
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
            exprs.append(self._search_expr())

        # User-supplied event-level filters (issue-level filters are excluded
        # at the `_needs_legacy_shape` dispatch point, so anything we see here
        # is purely event-level).
        if self.query.filterGroup and self.query.filterGroup.values:
            user_filter = self._filter_value_to_ast(self.query.filterGroup.values[0])
            if user_filter is not None:
                exprs.append(user_filter)

        return exprs

    def _outer_select_expressions(self) -> list[ast.Expr]:
        # `fp_state` is one row per fingerprint (LazyTable argmaxes by version);
        # after GROUP BY issue_id, multiple fingerprints may collapse into one
        # issue (issue merges). Per-issue scalar fields are picked with `any()`
        # since they're constant per issue. `first_seen` uses `min()` across the
        # merged fingerprints to preserve the earliest-known-first-seen.
        exprs: list[ast.Expr] = [
            ast.Alias(alias="id", expr=ast.Field(chain=["fp_state", "issue_id"])),
            ast.Alias(alias="status", expr=ast.Call(name="any", args=[ast.Field(chain=["fp_state", "issue_status"])])),
            ast.Alias(alias="name", expr=ast.Call(name="any", args=[ast.Field(chain=["fp_state", "issue_name"])])),
            ast.Alias(
                alias="description",
                expr=ast.Call(name="any", args=[ast.Field(chain=["fp_state", "issue_description"])]),
            ),
            ast.Alias(
                alias="assignee_user_id",
                expr=ast.Call(name="any", args=[ast.Field(chain=["fp_state", "assigned_user_id"])]),
            ),
            ast.Alias(
                alias="assignee_role_id",
                expr=ast.Call(name="any", args=[ast.Field(chain=["fp_state", "assigned_role_id"])]),
            ),
            ast.Alias(
                alias="first_seen",
                expr=ast.Call(name="min", args=[ast.Field(chain=["fp_state", "first_seen"])]),
            ),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["ev", "last_seen_fp"])])),
            ast.Alias(alias="function", expr=_merge("function_state", "argMax")),
            ast.Alias(alias="source", expr=_merge("source_state", "argMax")),
        ]

        if self.query.withAggregations:
            exprs.extend(
                [
                    ast.Alias(alias="occurrences", expr=ast.Call(name="sum", args=[ast.Field(chain=["ev", "occ"])])),
                    ast.Alias(alias="sessions", expr=_merge("sessions_state", "uniq")),
                    ast.Alias(alias="users", expr=_merge("users_state", "uniq")),
                    ast.Alias(alias="volumeRange", expr=_volume_range_expr(self.query.volumeResolution)),
                ]
            )

        if self.query.withFirstEvent:
            exprs.append(ast.Alias(alias="first_event_uuid", expr=_merge("first_event_uuid_state", "argMin")))

        if self.query.withLastEvent:
            exprs.append(ast.Alias(alias="last_event_uuid", expr=_merge("last_event_uuid_state", "argMax")))

        exprs.append(ast.Alias(alias="library", expr=_merge("library_state", "argMax")))

        return exprs

    def _outer_where_exprs(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = [
            ast.Call(name="isNotNull", args=[ast.Field(chain=["fp_state", "issue_id"])]),
        ]

        if self.query.issueId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["fp_state", "issue_id"]),
                    right=ast.Constant(value=self.query.issueId),
                )
            )

        if self.query.status and self.query.status != "all":
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["fp_state", "issue_status"]),
                    right=ast.Constant(value=self.query.status),
                )
            )

        if self.query.assignee:
            if self.query.assignee.type == "user":
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["fp_state", "assigned_user_id"]),
                        right=ast.Constant(value=self.query.assignee.id),
                    )
                )
            else:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["fp_state", "assigned_role_id"]),
                        right=ast.Constant(value=str(self.query.assignee.id)),
                    )
                )

        return exprs

    # ---------------------------------------------------------------------
    # Legacy single-query shape (mixed-OR filterGroup fallback)
    # ---------------------------------------------------------------------

    def _build_query_legacy(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self._select_expressions_legacy(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            where=ast.And(exprs=self._where_exprs_legacy()),
            group_by=[ast.Field(chain=["id"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=[self.query.orderBy]), order=order_direction(self.query))],
        )

    def _select_expressions_legacy(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = [
            ast.Alias(alias="id", expr=ast.Field(chain=["e", "issue_id_v2"])),
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
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["e", "timestamp"])])),
            ast.Alias(
                alias="first_seen",
                expr=ast.Call(name="min", args=[ast.Field(chain=["e", "issue_first_seen"])]),
            ),
            ast.Alias(alias="function", expr=innermost_frame_attribute("$exception_functions")),
            ast.Alias(alias="source", expr=innermost_frame_attribute("$exception_sources")),
        ]

        if self.query.withAggregations:
            # `uuid` is the events primary key, so `count(DISTINCT uuid)` is
            # identical to `count()` but pays for a distinct hashset per group.
            exprs.append(ast.Alias(alias="occurrences", expr=ast.Call(name="count", args=[])))
            # `uniq()` is HLL-based and ~1-2% off vs exact `count(DISTINCT)`
            # on high-cardinality inputs, but much cheaper.
            exprs.append(
                ast.Alias(
                    alias="sessions",
                    expr=ast.Call(
                        name="uniq",
                        args=[
                            ast.Call(
                                name="nullIf",
                                args=[ast.Field(chain=["e", "$session_id"]), ast.Constant(value="")],
                            )
                        ],
                    ),
                )
            )
            exprs.append(
                ast.Alias(
                    alias="users",
                    expr=ast.Call(
                        name="uniq",
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
                )
            )
            exprs.append(
                ast.Alias(
                    alias="volumeRange",
                    expr=select_sparkline_array(self.date_from, self.date_to, self.query.volumeResolution),
                )
            )

        # uuid-only here too — the runner attaches the event payloads in a second point lookup.
        if self.query.withFirstEvent:
            exprs.append(
                ast.Alias(
                    alias="first_event_uuid",
                    expr=ast.Call(
                        name="argMin", args=[ast.Field(chain=["e", "uuid"]), ast.Field(chain=["e", "timestamp"])]
                    ),
                )
            )

        if self.query.withLastEvent:
            exprs.append(
                ast.Alias(
                    alias="last_event_uuid",
                    expr=ast.Call(
                        name="argMax", args=[ast.Field(chain=["e", "uuid"]), ast.Field(chain=["e", "timestamp"])]
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

    def _where_exprs_legacy(self) -> list[ast.Expr]:
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
            exprs.append(self._search_expr())

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

        user_expr = self._user_filter_expr()
        if user_expr is not None:
            exprs.append(user_expr)

        return exprs

    # ---------------------------------------------------------------------
    # Shared helpers
    # ---------------------------------------------------------------------

    def _search_expr(self) -> ast.Expr:
        tokens = search_tokenizer(self.query.searchQuery or "")
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

        return ast.And(exprs=and_exprs)

    def _extract_assignee(self, row: dict) -> dict | None:
        user_id = row.get("assignee_user_id")
        role_id = row.get("assignee_role_id")
        if user_id:
            return {"id": int(user_id), "type": "user"}
        if role_id:
            return {"id": str(role_id), "type": "role"}
        return None

    def _user_filter_expr(self) -> ast.Expr | None:
        """Build a single AST expression for user-supplied filters from `filterGroup`,
        preserving nested OR/AND groups while routing issue-level filters to the
        denormalized issue fields. Only used by the legacy shape — the optimized
        shape calls `_filter_value_to_ast` directly from `_inner_where_exprs`
        because issue-level filters are guaranteed absent (see
        `_needs_legacy_shape`).
        """
        if not self.query.filterGroup or not self.query.filterGroup.values:
            return None
        return self._filter_value_to_ast(self.query.filterGroup.values[0])

    def _filter_value_to_ast(self, value: object) -> ast.Expr | None:
        if isinstance(value, ErrorTrackingIssueFilter):
            return self._issue_property_to_ast(value)

        if isinstance(value, PropertyGroupFilterValue):
            sub_exprs = [expr for child in value.values if (expr := self._filter_value_to_ast(child)) is not None]
            if not sub_exprs:
                return None
            if len(sub_exprs) == 1:
                return sub_exprs[0]
            if value.type == FilterLogicalOperator.OR_:
                return ast.Or(exprs=sub_exprs)
            return ast.And(exprs=sub_exprs)

        return property_to_expr(cast(Any, value), self.team, scope="event")

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
