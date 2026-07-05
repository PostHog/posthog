"""HogQL builders for focus-event occurrences, shared by the candidate query, estimate, and on-demand observe."""

import datetime as dt
from typing import Literal, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team

from products.replay_vision.backend.moments import MomentOccurrence, MomentsConfig

# One row is (timestamp, uuid, event); sorted before slicing so the kept subset — and therefore the
# anchors — is stable across sweep retries. groupArray's own cap bounds aggregation memory on
# pathological sessions; past it the kept subset can vary, which at worst yields different anchors on
# a retry — still capped per session and deduped per anchor.
_GROUP_ARRAY_CAP = 1_000
MAX_OCCURRENCES_PER_SESSION = 50

# On-demand observe can target any listed recording; bound the event scan to the replay retention ceiling.
_ON_DEMAND_LOOKBACK = dt.timedelta(days=90)
_ON_DEMAND_MAX_EXECUTION_SECONDS = 30


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
    # nosemgrep: hogql-fstring-audit (interpolates only module-level int constants and a literal fragment; runtime values go through placeholders)
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


def fetch_session_moment_occurrences(*, team: Team, config: MomentsConfig, session_id: str) -> list[MomentOccurrence]:
    """Focus-event occurrences within one session, for on-demand observe; sorted, capped like the sweep's."""
    # nosemgrep: hogql-fstring-audit (interpolates only a module-level int constant; runtime values go through placeholders)
    query = parse_select(
        f"""
        SELECT timestamp, toString(uuid) AS uuid, event
        FROM events
        WHERE $session_id = {{session_id}} AND timestamp >= {{occurred_after}} AND {{match}}
        ORDER BY timestamp ASC, uuid ASC
        LIMIT {MAX_OCCURRENCES_PER_SESSION}
        """,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "occurred_after": ast.Constant(value=dt.datetime.now(dt.UTC) - _ON_DEMAND_LOOKBACK),
            "match": occurrence_match_expr(config, team),
        },
    )
    with tags_context(product=Product.REPLAY_VISION, feature=Feature.QUERY):
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="ReplayVisionSessionMomentOccurrencesQuery",
            settings=HogQLGlobalSettings(max_execution_time=_ON_DEMAND_MAX_EXECUTION_SECONDS),
        )
    occurrences = []
    for timestamp, uuid, event in response.results or []:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.UTC)
        occurrences.append(MomentOccurrence(uuid=uuid, timestamp=timestamp, event=event))
    return occurrences
