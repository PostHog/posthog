import re
import datetime
from typing import Literal

from django.core.exceptions import ValidationError

from posthog.schema import ErrorTrackingQuery

from posthog.hogql import ast


def search_tokenizer(query: str) -> list[str]:
    # Splits on whitespace, keeping quoted strings together and stripping their quotes.
    pattern = r'"[^"]*"|\'[^\']*\'|\S+'
    tokens = re.findall(pattern, query)
    return [token.strip("'\"") for token in tokens]


def innermost_frame_attribute(materialized_col: str) -> ast.Call:
    return ast.Call(
        name="argMax",
        args=[
            ast.TupleAccess(tuple=ast.Field(chain=["properties", materialized_col]), index=-1),
            ast.Field(chain=["timestamp"]),
        ],
    )


def select_sparkline_array(date_from: datetime.datetime, date_to: datetime.datetime, resolution: int) -> ast.Call:
    start_time = ast.Call(name="toDateTime", args=[ast.Constant(value=date_from)])
    end_time = ast.Call(name="toDateTime", args=[ast.Constant(value=date_to)])
    total_size = ast.Call(name="dateDiff", args=[ast.Constant(value="seconds"), start_time, end_time])
    bin_size = ast.ArithmeticOperation(
        op=ast.ArithmeticOperationOp.Div, left=total_size, right=ast.Constant(value=resolution)
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
            ast.Call(name="range", args=[ast.Constant(value=0), ast.Constant(value=resolution)]),
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
    return ast.Call(name="sumForEach", args=[hot_indices])


def build_select_expressions(
    query: ErrorTrackingQuery, date_from: datetime.datetime, date_to: datetime.datetime
) -> list[ast.Expr]:
    """CH aggregation SELECT shared by V1 and the V2 inner subquery."""
    exprs: list[ast.Expr] = [
        ast.Alias(alias="id", expr=ast.Field(chain=["e", "issue_id"])),
        ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
        ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
        ast.Alias(alias="function", expr=innermost_frame_attribute("$exception_functions")),
        ast.Alias(alias="source", expr=innermost_frame_attribute("$exception_sources")),
    ]

    if query.withAggregations:
        exprs.extend(
            [
                ast.Alias(
                    alias="occurrences",
                    expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["uuid"])]),
                ),
                ast.Alias(
                    alias="sessions",
                    expr=ast.Call(
                        name="count",
                        distinct=True,
                        args=[ast.Call(name="nullIf", args=[ast.Field(chain=["$session_id"]), ast.Constant(value="")])],
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
                                            ast.Call(name="toString", args=[ast.Field(chain=["person_id"])]),
                                            ast.Constant(value="00000000-0000-0000-0000-000000000000"),
                                        ],
                                    ),
                                    ast.Field(chain=["distinct_id"]),
                                ],
                            )
                        ],
                    ),
                ),
                ast.Alias(alias="volumeRange", expr=select_sparkline_array(date_from, date_to, query.volumeResolution)),
            ]
        )

    if query.withFirstEvent:
        exprs.append(
            ast.Alias(
                alias="first_event",
                expr=ast.Call(
                    name="argMin",
                    args=[
                        ast.Tuple(
                            exprs=[
                                ast.Field(chain=["uuid"]),
                                ast.Field(chain=["distinct_id"]),
                                ast.Field(chain=["timestamp"]),
                                ast.Field(chain=["properties"]),
                            ]
                        ),
                        ast.Field(chain=["timestamp"]),
                    ],
                ),
            )
        )

    if query.withLastEvent:
        exprs.append(
            ast.Alias(
                alias="last_event",
                expr=ast.Call(
                    name="argMax",
                    args=[
                        ast.Tuple(
                            exprs=[
                                ast.Field(chain=["uuid"]),
                                ast.Field(chain=["distinct_id"]),
                                ast.Field(chain=["timestamp"]),
                                ast.Field(chain=["properties"]),
                            ]
                        ),
                        ast.Field(chain=["timestamp"]),
                    ],
                ),
            )
        )

    exprs.append(
        ast.Alias(
            alias="library",
            expr=ast.Call(
                name="argMax", args=[ast.Field(chain=["properties", "$lib"]), ast.Field(chain=["timestamp"])]
            ),
        )
    )

    return exprs


def build_event_where_exprs(
    query: ErrorTrackingQuery, date_from: datetime.datetime, date_to: datetime.datetime
) -> list[ast.Expr]:
    exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value="$exception"),
        ),
        ast.Call(name="isNotNull", args=[ast.Field(chain=["e", "issue_id"])]),
        ast.Placeholder(expr=ast.Field(chain=["filters"])),
    ]

    if date_from:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=date_from)]),
            )
        )

    if date_to:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=date_to)]),
            )
        )

    if query.issueId:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["e", "issue_id"]),
                right=ast.Constant(value=query.issueId),
            )
        )

    if query.personId:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["person_id"]),
                right=ast.Constant(value=query.personId),
            )
        )

    if query.groupKey and query.groupTypeIndex is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[f"$group_{query.groupTypeIndex}"]),
                right=ast.Constant(value=query.groupKey),
            )
        )

    if query.searchQuery:
        tokens = search_tokenizer(query.searchQuery)
        if len(tokens) > 100:
            raise ValidationError("Too many search tokens")

        and_exprs: list[ast.Expr] = []
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
                ("person", "properties"): ["email"],
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

    return exprs


def extract_event(event_tuple) -> dict | None:
    if event_tuple is None:
        return None
    return {
        "uuid": str(event_tuple[0]),
        "distinct_id": str(event_tuple[1]),
        "timestamp": str(event_tuple[2]),
        "properties": event_tuple[3],
    }


def volume_buckets(
    date_from: datetime.datetime, date_to: datetime.datetime, resolution: int
) -> list[datetime.datetime]:
    if resolution == 0:
        return []
    total_ms = (date_to - date_from).total_seconds() * 1000
    bin_size = int(total_ms / resolution)
    return [date_from + datetime.timedelta(milliseconds=i * bin_size) for i in range(resolution)]


def extract_aggregations(row: dict, date_from: datetime.datetime, date_to: datetime.datetime, resolution: int) -> dict:
    aggregations = {f: row[f] for f in ("occurrences", "sessions", "users", "volumeRange")}
    bins = volume_buckets(date_from, date_to, resolution)
    aggregations["volume_buckets"] = [
        {"label": b.isoformat(), "value": aggregations["volumeRange"][i] if aggregations["volumeRange"] else None}
        for i, b in enumerate(bins)
    ]
    return aggregations


def order_direction(query: ErrorTrackingQuery) -> Literal["ASC", "DESC"]:
    if query.orderDirection:
        return "ASC" if query.orderDirection.value == "ASC" else "DESC"
    return "ASC" if query.orderBy == "first_seen" else "DESC"
