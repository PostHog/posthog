"""Find session recordings a Replay Vision scanner should observe since its watermark.

A session is eligible when:
  - It's had no activity in the last 35 minutes (settle window), AND
  - Its end time is past the scanner's watermark.

Filter compilation defers to `SessionRecordingListFromQuery` so the scanner's
saved `RecordingsQuery` translates identically to what the recordings list does
for the same filters — minus `date_from` / `date_to` (the schedule controls time,
not the user).
"""

import datetime as dt
from dataclasses import dataclass
from typing import cast

import structlog
from opentelemetry import trace

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# 30-minute session-inactivity timeout + 5-minute settle buffer absorbs the
# AggregatingMergeTree merge lag on `session_replay_events`.
SETTLE_INTERVAL = dt.timedelta(minutes=35)

# Performance-only `date_from` on the inner query so ClickHouse can skip
# historical partitions. Sized above Vision's 1-hour active-seconds cap to
# absorb idle gaps in long sessions.
_PARTITION_LOOKBACK = dt.timedelta(hours=6)

# Sampling is stable per session via `cityHash64(session_id) % precision`.
SAMPLE_RATE_PRECISION = 10_000

# Per-fire candidate cap. Matches the master plan.
DEFAULT_CANDIDATE_LIMIT = 5_000

# A pathological filter must not be able to hang a scanner's schedule fire.
DEFAULT_MAX_EXECUTION_SECONDS = 180


@dataclass(frozen=True)
class CandidateSession:
    session_id: str
    # `max(max_last_timestamp)` for the session — the schedule advances its
    # watermark to `max(session_end)` of the returned batch.
    session_end: dt.datetime


class ScannerCandidateQuery:
    def __init__(
        self,
        *,
        team: Team,
        query: RecordingsQuery,
        last_swept_at: dt.datetime,
        sampling_rate: float,
        now: dt.datetime | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_execution_time_seconds: int = DEFAULT_MAX_EXECUTION_SECONDS,
    ) -> None:
        if not isinstance(last_swept_at, dt.datetime):
            raise TypeError(f"last_swept_at must be a datetime, got {type(last_swept_at).__name__}")
        if last_swept_at.tzinfo is None:
            raise ValueError("last_swept_at must be timezone-aware")
        if candidate_limit <= 0:
            raise ValueError(f"candidate_limit must be positive, got {candidate_limit}")

        self._team = team
        self._last_swept_at = last_swept_at
        self._sampling_rate = max(0.0, min(1.0, sampling_rate))
        self._candidate_limit = candidate_limit
        self._max_execution_time_seconds = max_execution_time_seconds
        self._now = now if now is not None else dt.datetime.now(dt.UTC)
        if self._now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        # The inner query handles all filter compilation. We control the time
        # window via date_from (partition prune) — the schedule, not the user,
        # owns the semantic watermark, applied in the outer WHERE.
        inner_query = query.model_copy(deep=True)
        inner_query.date_from = (last_swept_at - _PARTITION_LOOKBACK).isoformat()
        inner_query.date_to = None
        inner_query.limit = None
        inner_query.offset = None
        inner_query.after = None

        self._inner = SessionRecordingListFromQuery(team=team, query=inner_query)

    @tracer.start_as_current_span("ScannerCandidateQuery.run")
    def run(self) -> list[CandidateSession]:
        with tags_context(product=Product.REPLAY_VISION, feature=Feature.ENRICHMENT):
            response = execute_hogql_query(
                query=self.get_query(),
                team=self._team,
                query_type="ReplayVisionScannerCandidateQuery",
                settings=HogQLGlobalSettings(max_execution_time=self._max_execution_time_seconds),
            )
        return [CandidateSession(session_id=row[0], session_end=row[1]) for row in (response.results or [])]

    def get_query(self) -> ast.SelectQuery:
        inner = self._inner.get_query()
        # The inner query orders for the recordings-list use case; we apply our
        # own chronological ordering in the outer SELECT.
        inner.order_by = None

        where_exprs: list[ast.Expr] = [
            # Past the watermark.
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["sessions", "end_time"]),
                right=ast.Constant(value=self._last_swept_at),
            ),
            # No activity within the settle window.
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["sessions", "end_time"]),
                right=ast.Constant(value=self._now - SETTLE_INTERVAL),
            ),
        ]
        if (sampling := self._sampling_predicate()) is not None:
            where_exprs.append(sampling)

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["sessions", "session_id"]),
                ast.Alias(alias="session_end", expr=ast.Field(chain=["sessions", "end_time"])),
            ],
            select_from=ast.JoinExpr(table=cast(ast.SelectQuery, inner), alias="sessions"),
            where=ast.And(exprs=where_exprs),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["session_end"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["sessions", "session_id"]), order="ASC"),
            ],
            limit=ast.Constant(value=self._candidate_limit),
        )

    def _sampling_predicate(self) -> ast.Expr | None:
        if self._sampling_rate >= 1.0:
            return None
        threshold = max(0, int(self._sampling_rate * SAMPLE_RATE_PRECISION))
        if threshold <= 0:
            # Sampling out everything — emit `false` so the query plan stays trivial.
            return ast.Constant(value=False)
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=ast.Call(
                name="modulo",
                args=[
                    ast.Call(name="cityHash64", args=[ast.Field(chain=["sessions", "session_id"])]),
                    ast.Constant(value=SAMPLE_RATE_PRECISION),
                ],
            ),
            right=ast.Constant(value=threshold),
        )
