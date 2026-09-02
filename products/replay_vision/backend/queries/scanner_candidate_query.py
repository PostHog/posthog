"""Find session recordings a scanner should observe: ended past the watermark and quiet for 35+ minutes."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

import structlog
from opentelemetry import trace

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User
from posthog.session_recordings.queries.session_recording_list_from_query import (
    UNSCORED_SURFACING_SCORE,
    SessionRecordingListFromQuery,
)
from posthog.session_recordings.queries.sub_queries.group_key_resolver import GROUP_KEY_RESOLUTION_QUERY_TYPE

from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, SamplingMode
from products.replay_vision.backend.session_limits import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MAX_SESSION_ID_LENGTH,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# Partition prune anchored to the SDK's 24h session_id rotation + 2h headroom for skew and lag.
_PARTITION_LOOKBACK = dt.timedelta(hours=26)

# How far behind the watermark the frequent sweep's events subqueries scan. Covers the events of any
# session up to ~3h long plus skew; sessions whose matching events are older surface via the periodic
# deep sweep instead (see `find_scanner_candidates_activity`), which scans the full lookback.
SWEEP_EVENTS_LOOKBACK = dt.timedelta(hours=4)

# ClickHouse query-log tags. The read meter matches on these to attribute spend per pass, so a tag
# that drifts from its caller silently stops that pass being throttled.
BACKFILL_CANDIDATE_QUERY_TYPE = "ReplayVisionBackfillCandidateQuery"
BACKFILL_COUNT_QUERY_TYPE = "ReplayVisionBackfillCountQuery"
DEEP_SWEEP_CANDIDATE_QUERY_TYPE = "ReplayVisionDeepSweepCandidateQuery"
SWEEP_CANDIDATE_QUERY_TYPE = "ReplayVisionScannerCandidateQuery"
SWEEP_CANDIDATE_SCAN_QUERY_TYPE = "ReplayVisionScannerCandidateScanQuery"
EXCLUDED_SESSIONS_QUERY_TYPE = "ReplayVisionExcludedSessionsQuery"
BACKFILL_EXCLUDED_SESSIONS_QUERY_TYPE = "ReplayVisionBackfillExcludedSessionsQuery"

# The candidate-selection tags the read meter charges the frequent sweep's throttle on. A new
# selection query that is not listed here spends unmetered and never stretches the cadence. The
# one-shot priming query is deliberately outside it.
FAST_SWEEP_QUERY_TYPES = [
    SWEEP_CANDIDATE_QUERY_TYPE,
    SWEEP_CANDIDATE_SCAN_QUERY_TYPE,
    EXCLUDED_SESSIONS_QUERY_TYPE,
    GROUP_KEY_RESOLUTION_QUERY_TYPE,
]

SAMPLE_RATE_PRECISION = 10_000
# Smallest non-zero rate the modulo bucketing can express (one bucket); the API rejects non-zero rates below it.
MIN_SAMPLING_RATE = 1 / SAMPLE_RATE_PRECISION
DEFAULT_CANDIDATE_LIMIT = 5_000
# How many sessions one tick pulls into the correlated pass. Phase one is a keyset page over the
# replay table and costs a few MiB, so a page that turns out not to prune is nearly free.
CANDIDATE_SCAN_LIMIT = 2_000
DEFAULT_MAX_EXECUTION_SECONDS = 180

# Emitted by `emit_observation_event_activity` once an observation succeeds.
OBSERVATION_EVENT_NAME = "$recording_observed"

# Calibrated from the prod score distribution: focused keeps roughly the top 25% of sessions, balanced the top 65%.
FOCUSED_SURFACING_THRESHOLD = 0.30
BALANCED_SURFACING_THRESHOLD = 0.10
_SURFACING_THRESHOLDS = {
    SamplingMode.FOCUSED: FOCUSED_SURFACING_THRESHOLD,
    SamplingMode.BALANCED: BALANCED_SURFACING_THRESHOLD,
}


def surfacing_score_predicate(sampling_mode: SamplingMode | str) -> ast.Expr | None:
    """Quality pre-filter on the per-session surfacing score; None means no filter. Raises on unknown modes."""
    threshold = _SURFACING_THRESHOLDS.get(SamplingMode(sampling_mode))
    if threshold is None:
        return None
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Call(
            name="coalesce",
            args=[
                ast.Call(name="max", args=[ast.Field(chain=["s", "surfacing_score"])]),
                # Unscored sessions get the same neutral score the recordings list shows, so a session
                # visible as eligible in the UI is also eligible to the sweep.
                ast.Constant(value=UNSCORED_SURFACING_SCORE),
            ],
        ),
        right=ast.Constant(value=threshold),
    )


def eligibility_predicates() -> list[ast.Expr]:
    # Mirror the scan-time eligibility gate (fetch_session_events) on the same ClickHouse aggregates the scan reads, so
    # too-short/idle/long recordings never become candidates and the volume estimate counts the same eligible set. The
    # scan still re-checks these authoritatively; this only spares the wasted observation + metadata fetch each rejected
    # recording would otherwise cost.
    duration = ast.Field(chain=["duration"])
    active_seconds = ast.Field(chain=["active_seconds"])
    return [
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=duration,
            right=ast.Constant(value=MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=active_seconds,
            right=ast.Constant(value=MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=active_seconds,
            right=ast.Constant(value=MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
        ),
    ]


def execute_candidate_query(
    query: ast.SelectQuery, *, team: Team, query_type: str, max_execution_time_seconds: int, scanner_id: str | None
) -> list[list]:
    """One home for the candidate queries' ClickHouse execution policy.

    The dedicated user keeps sweep and backfill admission out of the contended shared `default` pool.
    """
    with tags_context(product=Product.REPLAY_VISION, feature=Feature.ENRICHMENT, scanner_id=scanner_id):
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type=query_type,
            settings=HogQLGlobalSettings(max_execution_time=max_execution_time_seconds),
            ch_user=ClickHouseUser.REPLAY_VISION,
        )
    return response.results or []


@dataclass(frozen=True)
class CandidateSession:
    session_id: str
    session_end: dt.datetime


@dataclass(frozen=True)
class CandidateBatch:
    """What one sweep tick considered and what it will dispatch.

    `keyset_end`/`keyset_session_id` mark the last session the tick *considered*, matched or not, so
    the watermark moves over ground actually covered rather than over the dispatch list. Advancing it
    past sessions that were fetched but never evaluated would drop them for good.
    """

    matched: list[CandidateSession]
    keyset_end: dt.datetime | None = None
    keyset_session_id: str = ""
    saturated: bool = False


class ScannerCandidateQuery:
    def __init__(
        self,
        *,
        team: Team,
        query: RecordingsQuery,
        last_swept_at: dt.datetime,
        sampling_rate: float,
        # The principal the recordings query runs as, for the experiment_exposure filter's access
        # check. The sweep passes the scanner's creator; a None principal makes that check refuse a
        # query carrying an exposure filter. A query without one is unaffected either way.
        user: User | None = None,
        # Per-scanner sampling salt (pass the scanner id); must stay stable across sweeps of the same scanner.
        sampling_salt: str,
        sampling_mode: SamplingMode | str = SamplingMode.COMPREHENSIVE,
        last_seen_session_id: str | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_execution_time_seconds: int = DEFAULT_MAX_EXECUTION_SECONDS,
        events_lookback: dt.timedelta | None = None,
        # The sweep drops negative-filter matches after fetching, so it turns the in-query blocklists
        # off and asks about its own candidates instead.
        skip_negative_blocklists: bool = False,
        # Tags the ClickHouse query for per-scanner read metering; sweep callers should always pass it.
        scanner_id: str | None = None,
    ) -> None:
        if not isinstance(last_swept_at, dt.datetime):
            raise TypeError(f"last_swept_at must be a datetime, got {type(last_swept_at).__name__}")
        if last_swept_at.tzinfo is None:
            raise ValueError("last_swept_at must be timezone-aware")
        if candidate_limit <= 0:
            raise ValueError(f"candidate_limit must be positive, got {candidate_limit}")
        if max_execution_time_seconds <= 0:
            raise ValueError(f"max_execution_time_seconds must be positive, got {max_execution_time_seconds}")

        self._team = team
        self._last_swept_at = last_swept_at
        self._last_seen_session_id = last_seen_session_id
        self._sampling_rate = max(0.0, min(1.0, sampling_rate))
        self._sampling_salt = sampling_salt
        self._candidate_limit = candidate_limit
        self._max_execution_time_seconds = max_execution_time_seconds
        self._scanner_id = scanner_id
        # Fixed at construction and exposed so callers can persist exactly the horizon the query filtered on.
        self.settle_cutoff = dt.datetime.now(dt.UTC) - SETTLE_INTERVAL

        # The schedule owns the time window, not the user.
        inner_query = query.model_copy(deep=True)
        inner_query.date_from = (last_swept_at - _PARTITION_LOOKBACK).isoformat()
        inner_query.date_to = None
        inner_query.limit = None
        inner_query.offset = None
        inner_query.after = None

        # Drop recordings the scan would reject anyway (too short / too idle / too long) before they become candidates,
        # then sample the rest — all in the inner HAVING, before outer aggregation.
        extra_having: list[ast.Expr] = eligibility_predicates()
        if (sampling := self._sampling_predicate()) is not None:
            extra_having.append(sampling)
        if (surfacing := surfacing_score_predicate(sampling_mode)) is not None:
            extra_having.append(surfacing)

        # Bounding positive events subqueries to a few hours keeps the every-few-minutes sweep from
        # re-scanning the full events lookback each tick. Exclusion blocklists ignore the floor (see
        # ReplayFiltersEventsSubQuery), so negative filters stay exact; a session whose only matching
        # event is older than the floor is missed here and caught by the deep sweep.
        events_timestamp_floor = (last_swept_at - events_lookback) if events_lookback is not None else None

        self._inner = SessionRecordingListFromQuery(
            team=team,
            query=inner_query,
            user=user,
            extra_having_predicates=extra_having,
            events_timestamp_floor=events_timestamp_floor,
            skip_negative_blocklists=skip_negative_blocklists,
            resolve_group_properties=ClickHouseUser.REPLAY_VISION,
        )

    def excluded_sessions_queries(self, session_ids: list[str]) -> list[ast.SelectQuery]:
        """Delegates, so the exclusion inherits the window and filters this query fetched with."""
        return self._inner.excluded_sessions_queries(session_ids)

    def matches_on_events(self) -> bool:
        """Whether `events_lookback` can cost this query candidates, so a deep pass has work to do."""
        return self._inner.matches_on_events()

    @tracer.start_as_current_span("ScannerCandidateQuery.run")
    def run(self) -> list[CandidateSession]:
        return self._execute(self.get_query(), SWEEP_CANDIDATE_QUERY_TYPE)

    @tracer.start_as_current_span("ScannerCandidateQuery.run_batch")
    def run_batch(self, dispatch_limit: int) -> CandidateBatch:
        return run_correlated_batch(
            build=self.get_query,
            execute=self._execute,
            scan_query_type=SWEEP_CANDIDATE_SCAN_QUERY_TYPE,
            match_query_type=SWEEP_CANDIDATE_QUERY_TYPE,
            dispatch_limit=dispatch_limit,
        )

    def _execute(self, query: ast.SelectQuery, query_type: str) -> list[CandidateSession]:
        rows = execute_candidate_query(
            query,
            team=self._team,
            query_type=query_type,
            max_execution_time_seconds=self._max_execution_time_seconds,
            scanner_id=self._scanner_id,
        )
        return [CandidateSession(session_id=row[0], session_end=row[1]) for row in rows]

    def get_query(self) -> ast.SelectQuery:
        # Building resolves group filters, which runs its own ClickHouse query. Tagging the build too
        # keeps that read attributable, so the throttle charges the sweep for it.
        with tags_context(product=Product.REPLAY_VISION, feature=Feature.ENRICHMENT, scanner_id=self._scanner_id):
            return self._build_query()

    def _build_query(self) -> ast.SelectQuery:
        # `_inner.get_query()` re-parses every call, so in-place mutation is safe.
        inner = self._inner.get_query()
        inner.order_by = None

        where_exprs: list[ast.Expr] = [
            self._watermark_predicate(),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["sessions", "end_time"]),
                right=ast.Constant(value=self.settle_cutoff),
            ),
            # Excludes attacker-supplied over-length session_ids that would later wedge wire-payload validation.
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Call(name="length", args=[ast.Field(chain=["sessions", "session_id"])]),
                right=ast.Constant(value=MAX_SESSION_ID_LENGTH),
            ),
        ]

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["sessions", "session_id"]),
                ast.Alias(alias="session_end", expr=ast.Field(chain=["sessions", "end_time"])),
            ],
            select_from=ast.JoinExpr(table=cast(ast.SelectQuery, inner), alias="sessions"),
            where=ast.And(exprs=where_exprs),
            order_by=keyset_order_by(ascending=True),
            limit=ast.Constant(value=self._candidate_limit),
        )

    def _watermark_predicate(self) -> ast.Expr:
        return keyset_predicate(self._last_swept_at, self._last_seen_session_id, ascending=True)

    def _sampling_predicate(self) -> ast.Expr | None:
        return sampling_predicate(self._sampling_rate, self._sampling_salt)


def run_correlated_batch(
    *,
    build: Callable[[], ast.SelectQuery],
    execute: Callable[[ast.SelectQuery, str], list[CandidateSession]],
    scan_query_type: str,
    match_query_type: str,
    dispatch_limit: int,
) -> CandidateBatch:
    """Name the candidate sessions first, then ask the events table only about those.

    Asking instead which sessions matched anywhere in the lookback makes ClickHouse read the team's
    whole event volume for that window and then throw nearly all of it away against the few hundred
    sessions the tick can dispatch. Listing the sessions up front lets the `$session_id` bloom filter
    prune the scan, which is where the saving comes from.
    """

    query = build()
    predicates = session_in_predicates(query)
    if not predicates:
        # No events subquery to correlate against, so splitting would only cost a second round trip.
        query.limit = ast.Constant(value=dispatch_limit)
        considered = execute(query, match_query_type)
        return build_candidate_batch(considered, considered, dispatch_limit, dispatch_limit)

    for predicate in predicates:
        _drop_event_filter(predicate)
    query.limit = ast.Constant(value=CANDIDATE_SCAN_LIMIT)
    considered = execute(query, scan_query_type)
    if not considered:
        return CandidateBatch(matched=[])

    matching = build()
    session_ids = [c.session_id for c in considered]
    for predicate in session_in_predicates(matching):
        _restrict_to_sessions(predicate, session_ids)
    # Also bound the outer query to the page. A filter whose operand is OR can match a session
    # through a non-event branch, which the subquery restriction never sees; without this the match
    # set could run past the page the keyset is computed from.
    _restrict_outer_to_sessions(matching, session_ids)
    matching.limit = ast.Constant(value=CANDIDATE_SCAN_LIMIT)
    matched = execute(matching, match_query_type)
    return build_candidate_batch(considered, matched, dispatch_limit, CANDIDATE_SCAN_LIMIT)


def session_in_predicates(query: ast.SelectQuery) -> list[ast.CompareOperation]:
    """Every `session_id in (events subquery)` predicate the compiled query carries.

    A scanner with test-account filters or event entities compiles to more than one. Restricting only
    the first leaves the others scanning the whole events window, which costs the entire saving while
    still returning the right sessions - a silent performance regression, not a visible failure.
    """
    inner = query.select_from.table if query.select_from else None
    if not isinstance(inner, ast.SelectQuery):
        return []
    collector = _SessionInCollector()
    collector.visit(inner.where)
    return collector.found


class _SessionInCollector(TraversingVisitor):
    """Collects the session-in predicates without descending into the subqueries they carry."""

    def __init__(self) -> None:
        self.found: list[ast.CompareOperation] = []

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if _is_session_in(node):
            self.found.append(node)
            return
        super().visit_compare_operation(node)


def _is_session_in(expr: ast.Expr) -> bool:
    return (
        isinstance(expr, ast.CompareOperation)
        and expr.op in (ast.CompareOperationOp.GlobalIn, ast.CompareOperationOp.In)
        and isinstance(expr.left, ast.Field)
        and expr.left.chain[-1] == "session_id"
        and isinstance(expr.right, ast.SelectQuery)
    )


def _drop_event_filter(predicate: ast.CompareOperation) -> None:
    """Turn the predicate into a tautology; this pass wants every session in the window."""
    predicate.op = ast.CompareOperationOp.Eq
    predicate.left = ast.Constant(value=1)
    predicate.right = ast.Constant(value=1)


def _restrict_to_sessions(predicate: ast.CompareOperation, session_ids: list[str]) -> None:
    subquery = predicate.right
    assert isinstance(subquery, ast.SelectQuery)
    selected = subquery.select[0]
    session_expr = selected.expr if isinstance(selected, ast.Alias) else selected
    restriction = ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=session_expr, right=ast.Constant(value=session_ids)
    )
    subquery.where = ast.And(exprs=[subquery.where, restriction]) if subquery.where else restriction


def _restrict_outer_to_sessions(query: ast.SelectQuery, session_ids: list[str]) -> None:
    restriction = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["sessions", "session_id"]),
        right=ast.Constant(value=session_ids),
    )
    query.where = ast.And(exprs=[query.where, restriction]) if query.where else restriction


def build_candidate_batch(
    considered: list[CandidateSession], matched: list[CandidateSession], dispatch_limit: int, scan_limit: int
) -> CandidateBatch:
    if len(matched) > dispatch_limit:
        # More matches than there is room to dispatch, so the walk stops at the last one that fits:
        # everything past it is re-considered next tick rather than skipped.
        matched = matched[:dispatch_limit]
        last = matched[-1]
        return CandidateBatch(
            matched=matched, keyset_end=last.session_end, keyset_session_id=last.session_id, saturated=True
        )
    if not considered:
        return CandidateBatch(matched=matched)
    last = considered[-1]
    return CandidateBatch(
        matched=matched,
        keyset_end=last.session_end,
        keyset_session_id=last.session_id,
        saturated=len(considered) >= scan_limit,
    )


def keyset_order_by(ascending: bool) -> list[ast.OrderExpr]:
    """Ordering the keyset predicate below assumes; the two have to move together."""
    direction: Literal["ASC", "DESC"] = "ASC" if ascending else "DESC"
    return [
        ast.OrderExpr(expr=ast.Field(chain=["session_end"]), order=direction),
        ast.OrderExpr(expr=ast.Field(chain=["sessions", "session_id"]), order=direction),
    ]


def keyset_predicate(end_time: dt.datetime, session_id: str | None, ascending: bool) -> ast.Expr:
    """Resume strictly past `(end_time, session_id)`, in whichever direction the query is ordered.

    Falls back to comparing the timestamp alone when there is no tiebreaker, which is the first pass
    over a window. Shared because a walk ordered one way and resumed the other silently skips rows.
    """
    field = ast.Field(chain=["sessions", "end_time"])
    op = ast.CompareOperationOp.Gt if ascending else ast.CompareOperationOp.Lt
    if not session_id:
        return ast.CompareOperation(op=op, left=field, right=ast.Constant(value=end_time))
    return ast.CompareOperation(
        op=op,
        left=ast.Tuple(exprs=[field, ast.Field(chain=["sessions", "session_id"])]),
        right=ast.Tuple(exprs=[ast.Constant(value=end_time), ast.Constant(value=session_id)]),
    )


def sampling_predicate(sampling_rate: float, sampling_salt: str) -> ast.Expr | None:
    """Deterministic salted-hash downsample on the inner query's session rows; None means keep everything."""
    if sampling_rate >= 1.0:
        return None
    # round(), not int(): float error puts e.g. 0.29 * 10_000 at 2899.999…, and truncation would shave a bucket.
    threshold = max(0, round(sampling_rate * SAMPLE_RATE_PRECISION))
    if threshold <= 0:
        return ast.Constant(value=False)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=ast.Call(
            name="modulo",
            args=[
                # concat rather than a second cityHash64 arg — HogQL pins cityHash64 to a single argument.
                ast.Call(
                    name="cityHash64",
                    args=[
                        ast.Call(
                            name="concat",
                            args=[ast.Field(chain=["s", "session_id"]), ast.Constant(value=sampling_salt)],
                        )
                    ],
                ),
                ast.Constant(value=SAMPLE_RATE_PRECISION),
            ],
        ),
        right=ast.Constant(value=threshold),
    )


class WindowedCandidateQuery:
    """Enumerate a scanner's candidate sessions inside a closed historical window.

    Same eligibility, sampling, and surfacing predicates as `ScannerCandidateQuery`, but bounded on both
    sides and walked newest-first: batches descend from `window_end` via a `(end_time, session_id)` keyset
    cursor. `count()` runs the identical predicate set without cursor or limit, so the creation-time
    enumeration is exactly the set the ticks will walk (the window is closed, so it can only shrink as
    recordings expire from retention — never grow).

    Two callers walk windows this way: backfills over a user-chosen range, and the sweep's deep pass
    over the range behind its own watermark. Each names its own reads, so a shared class cannot make
    one path's ClickHouse cost look like the other's.
    """

    def __init__(
        self,
        *,
        team: Team,
        query: RecordingsQuery,
        window_start: dt.datetime,
        window_end: dt.datetime,
        # Tags this caller's reads in `system.query_log`; required so a new caller names itself.
        query_type: str,
        sampling_rate: float,
        # The principal the recordings query runs as, for the experiment_exposure filter's access
        # check. The backfill passes whoever launched it; a None principal makes that check refuse a
        # query carrying an exposure filter. A query without one is unaffected either way.
        user: User | None = None,
        sampling_salt: str,
        sampling_mode: SamplingMode | str = SamplingMode.COMPREHENSIVE,
        cursor_end_time: dt.datetime | None = None,
        cursor_session_id: str | None = None,
        # Oldest-first. The catch-up pass walks this way so a batch that fills up can advance its
        # watermark to the last row instead of holding it: nothing older is left behind.
        ascending: bool = False,
        exclude_observed_by_scanner: str | None = None,
        # Session ids to drop inside the query. Unlike `exclude_observed_by_scanner` this comes from
        # the caller rather than from the `$recording_observed` event, so it can carry observations in
        # any state and cannot be influenced by ingested events.
        exclude_session_ids: list[str] | None = None,
        # Only for callers that drop negative-filter matches from the rows they fetched. The quote
        # path counts rather than dispatching, so it keeps the in-query blocklist and stays exact.
        skip_negative_blocklists: bool = False,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_execution_time_seconds: int = DEFAULT_MAX_EXECUTION_SECONDS,
        scanner_id: str | None = None,
    ) -> None:
        for name, value in (("window_start", window_start), ("window_end", window_end)):
            if not isinstance(value, dt.datetime):
                raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if window_start >= window_end:
            raise ValueError("window_start must be before window_end")
        if candidate_limit <= 0:
            raise ValueError(f"candidate_limit must be positive, got {candidate_limit}")

        self._team = team
        self._window_start = window_start
        self._window_end = window_end
        self._query_type = query_type
        self._ascending = ascending
        self._cursor_end_time = cursor_end_time
        self._cursor_session_id = cursor_session_id
        self._exclude_observed_by_scanner = exclude_observed_by_scanner
        self._exclude_session_ids = exclude_session_ids
        self._candidate_limit = candidate_limit
        self._max_execution_time_seconds = max_execution_time_seconds
        self._scanner_id = scanner_id

        # The backfill owns the time window; the frozen scanner query only contributes filters.
        inner_query = query.model_copy(deep=True)
        inner_query.date_from = (window_start - _PARTITION_LOOKBACK).isoformat()
        # Sessions end at or after their start, so no candidate in the window starts past window_end.
        inner_query.date_to = window_end.isoformat()
        inner_query.limit = None
        inner_query.offset = None
        inner_query.after = None

        extra_having: list[ast.Expr] = eligibility_predicates()
        if (sampling := sampling_predicate(sampling_rate, sampling_salt)) is not None:
            extra_having.append(sampling)
        if (surfacing := surfacing_score_predicate(sampling_mode)) is not None:
            extra_having.append(surfacing)

        self._inner = SessionRecordingListFromQuery(
            team=team,
            query=inner_query,
            user=user,
            extra_having_predicates=extra_having,
            session_ids_to_exclude=exclude_session_ids,
            skip_negative_blocklists=skip_negative_blocklists,
            resolve_group_properties=ClickHouseUser.REPLAY_VISION,
        )

    def excluded_sessions_queries(self, session_ids: list[str]) -> list[ast.SelectQuery]:
        """Delegates, so the exclusion inherits the window and filters this query fetched with."""
        return self._inner.excluded_sessions_queries(session_ids)

    @tracer.start_as_current_span("WindowedCandidateQuery.run")
    def run(self) -> list[CandidateSession]:
        return self._execute(self.get_query(), self._query_type)

    def _execute(self, query: ast.SelectQuery, query_type: str) -> list[CandidateSession]:
        rows = execute_candidate_query(
            query,
            team=self._team,
            query_type=query_type,
            max_execution_time_seconds=self._max_execution_time_seconds,
            scanner_id=self._scanner_id,
        )
        return [CandidateSession(session_id=row[0], session_end=row[1]) for row in rows]

    @tracer.start_as_current_span("WindowedCandidateQuery.count")
    def count(self, *, query_type: str) -> int:
        counted = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=self._windowed_candidates(), alias="candidates"),
        )
        rows = execute_candidate_query(
            counted,
            team=self._team,
            query_type=query_type,
            max_execution_time_seconds=self._max_execution_time_seconds,
            scanner_id=self._scanner_id,
        )
        return int(rows[0][0]) if rows else 0

    def get_query(self) -> ast.SelectQuery:
        query = self._windowed_candidates()
        if (cursor := self._cursor_predicate()) is not None:
            assert isinstance(query.where, ast.And)
            query.where.exprs.append(cursor)
        query.order_by = keyset_order_by(self._ascending)
        query.limit = ast.Constant(value=self._candidate_limit)
        return query

    def _windowed_candidates(self) -> ast.SelectQuery:
        """Window and eligibility predicates shared by the batch walk and the exact count."""
        # Tagged for the same reason as `ScannerCandidateQuery.get_query`: building resolves group
        # filters, and that read has to stay attributable to this scanner.
        with tags_context(product=Product.REPLAY_VISION, feature=Feature.ENRICHMENT, scanner_id=self._scanner_id):
            return self._build_windowed_candidates()

    def _build_windowed_candidates(self) -> ast.SelectQuery:
        # `_inner.get_query()` re-parses every call, so in-place mutation is safe.
        inner = self._inner.get_query()
        inner.order_by = None

        end_time = ast.Field(chain=["sessions", "end_time"])
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=end_time, right=ast.Constant(value=self._window_start)
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt, left=end_time, right=ast.Constant(value=self._window_end)
            ),
            # Excludes attacker-supplied over-length session_ids that would later wedge wire-payload validation.
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Call(name="length", args=[ast.Field(chain=["sessions", "session_id"])]),
                right=ast.Constant(value=MAX_SESSION_ID_LENGTH),
            ),
        ]
        if self._exclude_observed_by_scanner is not None:
            where_exprs.append(self._not_already_observed_predicate(self._exclude_observed_by_scanner))
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["sessions", "session_id"]),
                ast.Alias(alias="session_end", expr=ast.Field(chain=["sessions", "end_time"])),
            ],
            select_from=ast.JoinExpr(table=cast(ast.SelectQuery, inner), alias="sessions"),
            where=ast.And(exprs=where_exprs),
        )

    def _not_already_observed_predicate(self, scanner_id: str) -> ast.Expr:
        """Drop sessions this scanner already published a `$recording_observed` event for.

        Reads the event rather than shipping observation ids over from Postgres, so the exclusion is
        a plain ClickHouse join with no cross-database list and no size ceiling. The trade-off is that
        the event is only emitted on the success path, and fail-soft even there, so ineligible,
        failed, and in-flight observations stay in the count. Those cannot produce a second
        observation (the unique constraint blocks it), which is why the total is an upper bound.
        """
        observed = ast.SelectQuery(
            select=[ast.Field(chain=["properties", "session_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=OBSERVATION_EVENT_NAME),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["properties", "scanner_id"]),
                        right=ast.Constant(value=scanner_id),
                    ),
                    # An observation is always emitted after its session ended, so the window's own
                    # lower bound prunes partitions without ever excluding a relevant event.
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=self._window_start),
                    ),
                ]
            ),
        )
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotIn,
            left=ast.Field(chain=["sessions", "session_id"]),
            right=observed,
        )

    def _cursor_predicate(self) -> ast.Expr | None:
        if self._cursor_end_time is None:
            return None
        return keyset_predicate(self._cursor_end_time, self._cursor_session_id, ascending=self._ascending)
