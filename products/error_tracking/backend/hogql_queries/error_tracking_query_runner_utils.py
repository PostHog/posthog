import re
import datetime
from typing import Literal, overload
from uuid import UUID

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import ErrorTrackingOrderBy, ErrorTrackingQuery, ErrorTrackingQueryIssueSeverity

from posthog.hogql import ast


@overload
def validate_uuid_param(value: str, name: str) -> str: ...


@overload
def validate_uuid_param(value: None, name: str) -> None: ...


def validate_uuid_param(value: str | None, name: str) -> str | None:
    """Canonicalize a UUID query param, rejecting values ClickHouse could not parse.

    Returns the dashed-hex form: Python accepts looser formats (32 hex chars, braces,
    urn prefixes) that would still fail ClickHouse's UUID parsing at query time.
    DRF's ValidationError, not Django's: the query API only maps the DRF one to a 400.
    """
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        raise DRFValidationError(f"{name} must be a valid UUID")


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


def extract_event(event_tuple) -> dict | None:
    if event_tuple is None:
        return None
    return {
        "uuid": str(event_tuple[0]),
        "distinct_id": str(event_tuple[1]),
        # Keep ISO 8601, because the issue page copies this into its `timestamp` URL param for the replay player.
        "timestamp": event_tuple[2].isoformat(),
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
    aggregations = {f: row[f] for f in ("occurrences", "sessions", "users")}
    # volumeRange is only selected when a volume resolution was requested
    # (resolution=0 means counts only).
    aggregations["volumeRange"] = row["volumeRange"] if resolution > 0 else None
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


# Ascending order of seriousness. The sort rank of a row is its position in this list, so the
# order of the entries is the ranking itself. A new level in ErrorTrackingQueryIssueSeverity must
# get a place here as well, or it ranks the same as unset.
SEVERITY_RANKING: list[str] = [
    ErrorTrackingQueryIssueSeverity.LOW.value,
    ErrorTrackingQueryIssueSeverity.MEDIUM.value,
    ErrorTrackingQueryIssueSeverity.HIGH.value,
    ErrorTrackingQueryIssueSeverity.CRITICAL.value,
]


def order_by_exprs(query: ErrorTrackingQuery) -> list[ast.OrderExpr]:
    direction = order_direction(query)

    primary: ast.Expr = ast.Field(chain=[query.orderBy])
    if query.orderBy == ErrorTrackingOrderBy.SEVERITY:
        # Sorting on the `severity` column itself is wrong two ways, and both fail silently. It is a
        # Nullable(String), so the order is alphabetical (critical, high, low, medium), and ClickHouse
        # ranks NULL above every value, so DESC leads with the unset majority. Sort on the position in
        # SEVERITY_RANKING instead. `indexOf` gives 1 to 4 for a known level and 0 for a value that is
        # not in the array, and a NULL needle also gives 0, so unset ranks below `low`.
        primary = ast.Call(
            name="indexOf",
            args=[
                ast.Array(exprs=[ast.Constant(value=level) for level in SEVERITY_RANKING]),
                ast.Field(chain=["severity"]),
            ],
        )

    # The paginator pages with LIMIT/OFFSET over a re-run query, and ClickHouse returns tied rows in
    # any order, so tied rows move between pages and the infinite scroll repeats and drops them
    # unless the order is total. Small counts such as occurrences and users tie often, and so do the
    # few severity ranks. `last_seen` puts the most recently seen issue first within a tie, and `id`
    # is the GROUP BY key of both query shapes, so adding it makes the order total.
    tiebreakers = [
        ast.OrderExpr(expr=ast.Field(chain=[key]), order="DESC") for key in ("last_seen", "id") if key != query.orderBy
    ]
    return [ast.OrderExpr(expr=primary, order=direction), *tiebreakers]
