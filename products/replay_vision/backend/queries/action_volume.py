import datetime as dt
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

from products.actions.backend.facade.api import action_filter_conditions

# The same window the visited pages list uses, so a briefing can compare an action against a page.
_ACTION_WINDOW_DAYS = 7
# Actions are counted in one query, so the whole measurement shares this budget.
_ACTION_QUERY_MAX_EXECUTION_SECONDS = 5


def _any_of(conditions: list[ast.Expr]) -> ast.Expr:
    """One condition unchanged, or several ORed. `ast.Or` needs at least two operands."""
    return conditions[0] if len(conditions) == 1 else ast.Or(exprs=conditions)


def recent_action_sessions(
    *,
    team: Team,
    action_ids: Sequence[int],
    window_days: int = _ACTION_WINDOW_DAYS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> dict[int, int]:
    """How many sessions each action fired in over a recent window, keyed by action id.

    An action is a saved definition, not collected data, so it outlives the thing it describes. An
    autocapture action keyed to a button's text stops matching when the copy changes, and nothing on
    the action records that it went quiet. Measuring is the only way to tell a live action from one
    that has matched nothing for years.

    A count of 0 means the action fired in no session in the window. An action absent from the result
    could not be read, or does not compile to a filter.

    Raises on query failure, so the caller decides whether a missing measurement is fatal.
    """
    conditions = action_filter_conditions(team=team, action_ids=action_ids)
    if not conditions:
        return {}

    measured = list(conditions)
    columns: list[ast.Expr] = [
        ast.Alias(
            alias=f"action_{action_id}",
            expr=ast.Call(name="uniqIf", args=[ast.Field(chain=["$session_id"]), condition]),
        )
        for action_id, condition in conditions.items()
    ]

    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = ast.SelectQuery(
        select=columns,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=window_start),
                ),
                # Narrows the scan to events at least one action can match, so the cost tracks the
                # actions asked about and not the team's whole event volume. Cloned because the
                # resolver annotates the nodes it walks, and these also sit in the SELECT.
                _any_of([clone_expr(condition) for condition in conditions.values()]),
            ]
        ),
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionActionVolumeQuery",
        # "throw", not "break": a partial aggregate reads as a live action that went quiet, which is
        # the exact distinction this query exists to make.
        settings=HogQLGlobalSettings(
            max_execution_time=_ACTION_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw"
        ),
        ch_user=ch_user,
    )
    rows = response.results or []
    if not rows:
        return dict.fromkeys(measured, 0)
    return {action_id: int(count) for action_id, count in zip(measured, rows[0])}
