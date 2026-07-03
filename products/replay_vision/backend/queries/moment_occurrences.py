"""HogQL builders for focus-event occurrences, shared by the candidate query and the volume estimate."""

import datetime as dt
from typing import Literal, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.models import Team

from products.replay_vision.backend.moments import MomentsConfig

# One row is (timestamp, uuid, event); sorted before slicing so the kept subset — and therefore the
# anchors — is stable across sweep retries. groupArray's own cap bounds aggregation memory on
# pathological sessions; past it the kept subset can vary, which at worst yields different anchors on
# a retry — still capped per session and deduped per anchor.
_GROUP_ARRAY_CAP = 1_000
MAX_OCCURRENCES_PER_SESSION = 50


def occurrence_match_expr(config: MomentsConfig, team: Team) -> ast.Expr:
    """OR over the focus events: (event = X AND its property filters) OR (...)."""
    branches: list[ast.Expr] = []
    for moment_event in config.events:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=moment_event.event),
            )
        ]
        if moment_event.properties:
            exprs.append(property_to_expr(moment_event.properties, team))
        branches.append(ast.And(exprs=exprs) if len(exprs) > 1 else exprs[0])
    return ast.Or(exprs=branches) if len(branches) > 1 else branches[0]


def moment_occurrences_subquery(
    *,
    team: Team,
    config: MomentsConfig,
    occurred_after: dt.datetime,
    aggregate: Literal["occurrences", "count"],
) -> ast.SelectQuery:
    """Per-session focus-event aggregation, for joining against the candidate/estimate session set.

    `occurrences` yields `arraySort`ed `(timestamp, uuid, event)` tuples capped at
    MAX_OCCURRENCES_PER_SESSION; `count` yields a plain `occurrence_count` for the estimate.
    """
    if aggregate == "occurrences":
        # Module-constant ints interpolated directly — the parametric aggregate position can't take a placeholder.
        select = (
            f"arraySlice(arraySort(groupArray({_GROUP_ARRAY_CAP})((timestamp, toString(uuid), event))), "
            f"1, {MAX_OCCURRENCES_PER_SESSION}) AS occurrences"
        )
    else:
        select = "count() AS occurrence_count"
    query = parse_select(
        f"""
        SELECT $session_id AS session_id, {select}
        FROM events
        WHERE timestamp >= {{occurred_after}} AND notEmpty($session_id) AND {{match}}
        GROUP BY session_id
        """,
        placeholders={
            "occurred_after": ast.Constant(value=occurred_after),
            "match": occurrence_match_expr(config, team),
        },
    )
    return cast(ast.SelectQuery, query)
