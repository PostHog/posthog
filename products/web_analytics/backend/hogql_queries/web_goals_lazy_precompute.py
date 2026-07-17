"""Lazy precompute path for the Web Analytics GOALS tile.

Mirrors `web_stats_paths_lazy_precompute.py` and shares its eligibility gate
via `web_lazy_precompute_common`. The precomputed table stores one row per
(team, job, UTC hour, action_id):

- `action_id = -1` carries the per-hour denominator: unique persons whose
  session had ANY qualifying event (pageview / screen / action match).
- `action_id = <real id>` carries the per-action conversion: sum of match
  counts plus unique converting persons.

The action set (the top-5 actions returned by
`Action.objects…order_by('pinned_at', '-last_calculated_at')[:5]`) is part
of the INSERT AST and therefore the lazy_computation cache key — a different
top-5 set yields a different job_id, so the runner's hard `[:5]` slice is
mirrored without further coordination.
"""

import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.actions.backend.models.action import Action
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    LazyPrecomputeIneligible,
    ceil_utc_day,
    check_common_eligibility,
    floor_utc_day,
    handle_stale_served,
    host_filter_expr,
    log_eligibility_outcome,
    test_account_filter_expr,
    web_ensure_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_goals import WebGoalsQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_goals"


# Sentinel action_id used for the per-hour denominator row. Real Django
# `Action.id` values are positive auto-increment integers, so -1 is safe.
DENOMINATOR_ACTION_ID = -1

# Maximum number of actions the precompute will cover. Matches the runner's
# hard `Action.objects…[:5]` slice exactly — precomputing more would be
# wasted INSERT work the runner never reads. If the live UX ever expands
# beyond 5 actions, bump both this constant and the runner's slice together.
MAX_ACTIONS = 5


_KNOWN_FAILED_ERROR_TYPES: set[str] = {
    "ServerException",
    "NetworkError",
    "OperationalError",
    "IntegrityError",
    "AssertionError",
    "AttributeError",
    "KeyError",
    "ValueError",
    "TypeError",
    "TimeoutError",
}


def _bucket_error_label(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in _KNOWN_FAILED_ERROR_TYPES else "other"


WEB_GOALS_LAZY_FAILED = Counter(
    "web_goals_lazy_precompute_failed_total",
    "Lazy precompute path (goals tile) failures, by error class",
    ["error_type"],
)

WEB_GOALS_LAZY_EMPTY = Counter(
    "web_goals_lazy_precompute_empty_total",
    "Lazy precompute reads that returned zero rows (no qualifying sessions).",
)

WEB_GOALS_LAZY_ACTIONS = Histogram(
    "web_goals_lazy_precompute_actions",
    "Number of actions the precompute job covered (cap at MAX_ACTIONS).",
    buckets=(1, 2, 3, 4, 5),
)


class NoActionsConfigured(LazyPrecomputeIneligible):
    pass


def can_use_lazy_precompute(runner: "WebGoalsQueryRunner") -> bool:
    """Return True iff the GOALS tile can be served from precompute."""
    try:
        _check_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        log_eligibility_outcome(log_prefix="web_goals_lazy_precompute", team_id=runner.team.pk, error=exc)
        return False
    log_eligibility_outcome(log_prefix="web_goals_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def _check_eligible(runner: "WebGoalsQueryRunner") -> None:
    query = runner.query

    check_common_eligibility(
        team=runner.team,
        use_web_analytics_precompute=query.useWebAnalyticsPrecompute,
        conversion_goal=None,
        sampling=query.sampling,
        modifiers=query.modifiers,
        properties=query.properties or [],
        resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
    )

    # We need at least one action — without any, the live runner raises
    # `NoActionsError` and returns an empty response; the lazy path has
    # nothing to precompute either.
    if _select_actions(runner) == []:
        raise NoActionsConfigured()


# Attribute name used to memoize the action lookup on the per-request
# runner instance. Using a `_lazy_*` prefix avoids collision with anything
# the live `WebGoalsQueryRunner` already stores.
_RUNNER_ACTIONS_CACHE_ATTR = "_lazy_goals_actions"


def _select_actions(runner: "WebGoalsQueryRunner") -> list:
    """Top-N actions, matching the live runner's hard `[:5]` slice exactly.

    Memoized on the runner instance: this function is called from both the
    eligibility check (`_check_eligible`) and the orchestrator
    (`execute_lazy_precomputed_read`). Without caching we issue two
    consecutive identical Postgres queries per opted-in request AND open a
    TOCTOU window where a concurrent action mutation between the two calls
    can flip eligibility from "pass with N actions" to "execute with 0
    actions", producing a confusing empty-then-fallback response. The
    runner is request-scoped, so a per-runner attribute cache is the right
    lifetime.

    Different top-5 sets across requests still produce different INSERT
    ASTs and therefore distinct lazy_computation cache keys — the cache
    here is purely an in-request memoization.
    """
    cached = getattr(runner, _RUNNER_ACTIONS_CACHE_ATTR, None)
    if cached is not None:
        return cached
    qs = Action.objects.filter(team__project_id=runner.team.project_id, deleted=False).order_by(
        "pinned_at", "-last_calculated_at"
    )[:MAX_ACTIONS]
    fetched = list(qs)
    setattr(runner, _RUNNER_ACTIONS_CACHE_ATTR, fetched)
    return fetched


def _events_session_id_expr(runner: "WebGoalsQueryRunner") -> ast.Expr:
    return runner.events_session_property


def _action_or_expr(actions: Sequence) -> ast.Expr:
    """Build `Or(action_to_expr(a) for a in actions)` — gates the events scan
    to events that can possibly contribute to any of the actions, plus
    `$pageview`/`$screen` which always anchor the session."""
    return ast.Or(exprs=[action_to_expr(a) for a in actions])


def _build_insert_query(actions: Sequence) -> str:
    """Synthesize the HogQL INSERT template for the given action set.

    The shape is one row per (team, job, hour, action_id) emitted by:
    - inner session aggregation that produces per-session
      `count_<n>` columns (one per action) plus `session_person_id`
    - `arrayJoin` over `[(-1, 0), (action_0_id, count_0), ..., (action_N_id,
      count_N)]` that fans those columns out into rows
    - outer `GROUP BY toStartOfHour(start_timestamp), action_id` that emits
      `sumState(action_count)` and `uniqStateIf(session_person_id, ...)`

    `action_id = -1` aggregates the per-hour denominator (every session's
    person), giving the global "converting universe" the runner uses to
    compute conversion rate. The condition `action_id = -1 OR action_count
    > 0` keeps unique-person counts honest for both the per-action and
    denominator rows in one expression.
    """
    # Per-session COUNT columns + ORM-known action ids for the arrayJoin.
    # Every tuple element is wrapped in an explicit `toInt(...)` so the
    # tuple types unify cleanly across the array. ClickHouse requires
    # uniform element types within an array of tuples; without the explicit
    # cast the denominator's literal `0` (Int32) and the per-action
    # `countIf(...)` (UInt64) would force ClickHouse into type-unification
    # rules that have historically produced runtime errors in similar
    # precompute paths, and the round-trip parity test is skipped pending
    # the read-after-write CI flake — so a type error would only surface in
    # production through the failure counter and silent fall-through to the
    # live path. (HogQL exposes `toInt`, which compiles to ClickHouse's
    # `toInt64`; `toInt64` itself is not a valid HogQL identifier.)
    # `countIf` is bounded by the per-job time window so events that occur
    # in the SESSION_FORWARD_PAD_MINUTES tail (past `time_window_max`) do
    # NOT contribute to this job's counts. The pad lets `min(start_timestamp)`
    # see late events for correct session-start anchoring, but counting them
    # here would overcount conversions for sessions starting near the end of
    # the user's selected range — the live runner counts goals with
    # `countIf(action_expr AND timestamp IN current_period)`, so the lazy
    # match it event-by-event rather than aggregating the whole session's
    # event tail into the start-hour bucket.
    count_aliases = ",\n            ".join(
        f"countIf(and({{action_{n}_expr}}, timestamp >= {{time_window_min}}, timestamp < {{time_window_max}})) AS count_{n}"
        for n in range(len(actions))
    )
    array_join_pairs = ",\n            ".join(
        f"tuple({{action_{n}_id}}, toInt(count_{n}))" for n in range(len(actions))
    )
    # The literal `-1` anchors the per-hour denominator row; `0` is just a
    # placeholder because the denominator row's `count_state` is never read.
    array_join_literal = f"tuple(toInt({DENOMINATOR_ACTION_ID}), toInt(0)), {array_join_pairs}"

    return f"""
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    action_id AS action_id,
    sumState(assumeNotNull(toInt(action_count))) AS count_state,
    uniqStateIf(
        session_person_id,
        or(equals(action_id, {DENOMINATOR_ACTION_ID}), greater(action_count, 0))
    ) AS unique_persons_state
FROM (
    SELECT
        start_timestamp,
        session_person_id,
        arrayJoin([
            {array_join_literal}
        ]) AS pair,
        pair.1 AS action_id,
        pair.2 AS action_count
    FROM (
        SELECT
            any(events.person_id) AS session_person_id,
            min(session.$start_timestamp) AS start_timestamp,
            {{events_session_id}} AS session_id,
            {count_aliases}
        FROM events
        WHERE and(
            {{events_session_id}} IS NOT NULL,
            or(events.event = '$pageview', events.event = '$screen', {{action_or_expr}}),
            timestamp >= {{time_window_min}},
            timestamp < ({{time_window_max}} + toIntervalMinute({{pad_minutes}})),
            {{user_filter}},
            {{test_account_filter}}
        )
        GROUP BY session_id
        HAVING and(
            toStartOfHour(min(session.$start_timestamp)) >= {{time_window_min}},
            toStartOfHour(min(session.$start_timestamp)) < {{time_window_max}}
        )
    )
)
GROUP BY time_window_start, action_id
"""


def ensure_web_goals_precomputed(
    runner: "WebGoalsQueryRunner",
    actions: Sequence,
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "action_or_expr": _action_or_expr(actions),
        "user_filter": host_filter_expr(runner.query.properties or [], team=runner.team),
        "test_account_filter": test_account_filter_expr(
            test_account_filters=runner._test_account_filters, team=runner.team
        ),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }
    for n, action in enumerate(actions):
        placeholders[f"action_{n}_expr"] = action_to_expr(action)
        placeholders[f"action_{n}_id"] = ast.Constant(value=int(action.id))

    return web_ensure_precomputed(
        team=runner.team,
        insert_query=_build_insert_query(actions),
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_GOALS_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_goals_lazy_insert",
        spill_to_disk=True,  # per-action GROUP BY over a sessions join; can build a large hash table
    )


# Soft budget for the cumulative `ensure_precomputed` time inside a single
# request. Same reasoning as the paths tile: a compare-period request makes
# two back-to-back ensure calls and the framework's default per-call wait is
# 180s — skip the second if the first already burned most of that.
ENSURE_BUDGET_MS = 120 * 1000


# Read template. One row per `action_id` (including the `-1` denominator) for
# the requested current + previous periods. The HAVING is intentionally absent —
# the runner needs every requested `action_id` in the response (even if 0
# converted) so action_name lookups don't surface as missing rows.
_READ_SQL_TEMPLATE = """
SELECT
    action_id,
    sumMergeIf(count_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS current_total,
    sumMergeIf(count_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_total,
    uniqMergeIf(unique_persons_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS current_unique,
    uniqMergeIf(unique_persons_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_unique
FROM posthog.web_goals_preaggregated
WHERE and(team_id = {team_id}, job_id IN {job_ids}, action_id IN {action_ids})
GROUP BY action_id
"""


def execute_read_query(
    *,
    runner: "WebGoalsQueryRunner",
    job_ids: list[str],
    action_ids: list[int],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> list:
    """Run the precompute-read HogQL. Returns raw `response.results`."""
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Constant(value=[str(jid) for jid in job_ids]),
        "action_ids": ast.Constant(value=action_ids),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "prev_start": ast.Constant(value=prev_start),
        "prev_end": ast.Constant(value=prev_end),
    }

    parsed = parse_select(_READ_SQL_TEMPLATE, placeholders=placeholders)
    assert isinstance(parsed, ast.SelectQuery), "lazy goals read template must parse to a SelectQuery"

    modifiers = runner.modifiers.model_copy() if runner.modifiers else HogQLQueryModifiers()
    modifiers.convertToProjectTimezone = False

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_goals_lazy_query")
    response = execute_hogql_query(
        query_type="web_goals_lazy_query",
        query=parsed,
        team=runner.team,
        timings=runner.timings,
        modifiers=modifiers,
        limit_context=runner.limit_context,
    )
    return list(response.results or [])


def execute_lazy_precomputed_read(runner: "WebGoalsQueryRunner") -> Optional[dict]:
    """Orchestrate the lazy precompute + read. Returns a dict with the action
    list and the per-action / denominator metrics, or None on any failure
    (caller falls through to the live HogQL path).

    Output shape:
        {
            "actions": [Action, ...],  # top-N in order
            "denominator": {"current": int, "previous": int},
            "per_action": {
                action_id: {
                    "current_total": int,
                    "previous_total": int,
                    "current_unique": int,
                    "previous_unique": int,
                },
                ...
            },
        }
    """
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        actions = _select_actions(runner)
        if not actions:
            return None
        WEB_GOALS_LAZY_ACTIONS.observe(len(actions))

        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            logger.info(
                "web_goals_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_goals_lazy_precompute_started",
            team_id=team_id,
            action_count=len(actions),
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_web_goals_precomputed(
            runner=runner,
            actions=actions,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)
        logger.info(
            "web_goals_lazy_precompute_ensure_done",
            team_id=team_id,
            job_count=len(result.job_ids),
            ensure_duration_ms=ensure_duration_ms,
        )
        if result.stale:
            handle_stale_served(runner=runner, family=_FAMILY)

        if not result.job_ids or not result.ready:
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            if prev_from is not None and prev_to is not None:
                previous_start_utc = prev_from.astimezone(UTC)
                previous_end_utc = prev_to.astimezone(UTC)
                prev_range_start = floor_utc_day(previous_start_utc)
                prev_range_end = ceil_utc_day(previous_end_utc)
                if prev_range_start < prev_range_end:
                    if ensure_duration_ms >= ENSURE_BUDGET_MS:
                        logger.info(
                            "web_goals_lazy_precompute_compare_budget_exceeded",
                            team_id=team_id,
                            elapsed_ms=ensure_duration_ms,
                            budget_ms=ENSURE_BUDGET_MS,
                        )
                        return None
                    prev_ensure_started = time.perf_counter()
                    prev_result = ensure_web_goals_precomputed(
                        runner=runner,
                        actions=actions,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                    )
                    ensure_duration_ms += int((time.perf_counter() - prev_ensure_started) * 1000)
                    if prev_result.stale:
                        # handle_stale_served enqueues at most once per request; one
                        # revalidation re-runs the whole query, covering both periods.
                        handle_stale_served(runner=runner, family=_FAMILY)
                    if not prev_result.ready:
                        logger.info(
                            "web_goals_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None
                    job_ids.extend(str(jid) for jid in prev_result.job_ids)

        action_ids = [DENOMINATOR_ACTION_ID, *[int(a.id) for a in actions]]
        read_started = time.perf_counter()
        rows = execute_read_query(
            runner=runner,
            job_ids=job_ids,
            action_ids=action_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)
        total_duration_ms = int((time.perf_counter() - overall_started) * 1000)

        if not rows:
            WEB_GOALS_LAZY_EMPTY.inc()
            logger.info(
                "web_goals_lazy_precompute_no_rows",
                team_id=team_id,
                job_count=len(result.job_ids),
            )
            return None

        denominator = {"current": 0, "previous": 0}
        per_action: dict[int, dict[str, int]] = {}
        for action_id, current_total, previous_total, current_unique, previous_unique in rows:
            if int(action_id) == DENOMINATOR_ACTION_ID:
                denominator = {"current": int(current_unique), "previous": int(previous_unique)}
                continue
            per_action[int(action_id)] = {
                "current_total": int(current_total),
                "previous_total": int(previous_total),
                "current_unique": int(current_unique),
                "previous_unique": int(previous_unique),
            }

        logger.info(
            "web_goals_lazy_precompute_completed",
            team_id=team_id,
            job_count=len(result.job_ids),
            rows_returned=len(rows),
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        return {
            "actions": actions,
            "denominator": denominator,
            "per_action": per_action,
        }
    except Exception as exc:
        WEB_GOALS_LAZY_FAILED.labels(error_type=_bucket_error_label(exc)).inc()
        logger.exception(
            "web_goals_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
