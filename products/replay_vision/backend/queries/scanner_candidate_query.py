"""Find session recordings a scanner should observe: ended past the watermark and quiet for 35+ minutes."""

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

from products.replay_vision.backend.temporal.constants import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# 30-min inactivity timeout + 5-min merge-lag buffer.
SETTLE_INTERVAL = dt.timedelta(minutes=35)

# Partition prune anchored to the SDK's 24h session_id rotation + 2h headroom for skew and lag.
_PARTITION_LOOKBACK = dt.timedelta(hours=26)

SAMPLE_RATE_PRECISION = 10_000
# Smallest non-zero rate the modulo bucketing can express (one bucket); the API rejects non-zero rates below it.
MIN_SAMPLING_RATE = 1 / SAMPLE_RATE_PRECISION
DEFAULT_CANDIDATE_LIMIT = 5_000
DEFAULT_MAX_EXECUTION_SECONDS = 180

# Excludes attacker-supplied over-length session_ids that would later wedge wire-payload validation.
_MAX_SESSION_ID_LENGTH = 128


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


@dataclass(frozen=True)
class CandidateSession:
    session_id: str
    session_end: dt.datetime


class ScannerCandidateQuery:
    def __init__(
        self,
        *,
        team: Team,
        query: RecordingsQuery,
        last_swept_at: dt.datetime,
        sampling_rate: float,
        # Salts the sampling hash (pass the scanner id) so each scanner draws an independent sample; must be
        # stable across sweeps of the same scanner or sessions would flip in/out behind the watermark.
        sampling_salt: str,
        last_seen_session_id: str | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        max_execution_time_seconds: int = DEFAULT_MAX_EXECUTION_SECONDS,
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

        self._inner = SessionRecordingListFromQuery(team=team, query=inner_query, extra_having_predicates=extra_having)

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
        # `_inner.get_query()` re-parses every call, so in-place mutation is safe.
        inner = self._inner.get_query()
        inner.order_by = None

        where_exprs: list[ast.Expr] = [
            self._watermark_predicate(),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["sessions", "end_time"]),
                right=ast.Constant(value=dt.datetime.now(dt.UTC) - SETTLE_INTERVAL),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Call(name="length", args=[ast.Field(chain=["sessions", "session_id"])]),
                right=ast.Constant(value=_MAX_SESSION_ID_LENGTH),
            ),
        ]

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

    def _watermark_predicate(self) -> ast.Expr:
        end_time = ast.Field(chain=["sessions", "end_time"])
        watermark = ast.Constant(value=self._last_swept_at)
        strict = ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=end_time, right=watermark)
        if self._last_seen_session_id is None:
            return strict
        # Lexicographic tuple comparison gives keyset semantics for resuming past saturated batches.
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Tuple(exprs=[end_time, ast.Field(chain=["sessions", "session_id"])]),
            right=ast.Tuple(exprs=[watermark, ast.Constant(value=self._last_seen_session_id)]),
        )

    def _sampling_predicate(self) -> ast.Expr | None:
        if self._sampling_rate >= 1.0:
            return None
        # round(), not int(): float error puts e.g. 0.29 * 10_000 at 2899.999…, and truncation would shave a bucket.
        threshold = max(0, round(self._sampling_rate * SAMPLE_RATE_PRECISION))
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
                                args=[ast.Field(chain=["s", "session_id"]), ast.Constant(value=self._sampling_salt)],
                            )
                        ],
                    ),
                    ast.Constant(value=SAMPLE_RATE_PRECISION),
                ],
            ),
            right=ast.Constant(value=threshold),
        )
