"""The AI member of the `default-v2` profile: the judge confirms or rejects the buckets that z-score flagged.

A bucket that z-score does not flag makes no model call. A flagged bucket is asked about within the caps:
per insight per run, newest buckets first, and per project per UTC day. A score step fetches the judge's history
only when the caps allow a call and the organization consents to AI data processing. A bucket the judge rejects
keeps its z-score score and gets flag 0. A flagged bucket the judge was not asked about, or could not answer,
keeps its flag, and its details say why. `$anomaly_details` holds each member's result, so the z-score flag stays
readable.
"""

import time
import datetime
import dataclasses
from collections.abc import Callable
from typing import Any

from django.core.cache import cache
from django.utils import timezone

import numpy as np
import structlog

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.tasks.alerts.detector import llm_detector_lookback
from posthog.tasks.alerts.metric_definition import MetricDateRange, describe_metric_definition

from products.alerts.backend.facade.lazy_judge import (
    MAX_JUDGE_CALL_SECONDS,
    EarlierFlag,
    JudgeMemberResult,
    MemberState,
    NotEvaluatedReason,
    SeriesContext,
    combined_flag,
    judge_flagged_bucket,
    not_evaluated,
)
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import DEFAULT_LIMITS, AIJudgeConfig, ScoringLimits
from products.signals.backend.anomaly_scores.scoring import (
    FetchedSeries,
    InsightScores,
    ScoredPoint,
    ScoredSeries,
    fetch_judge_history,
)

logger = structlog.get_logger(__name__)

# Own product key in LLM analytics, apart from the alert AI detector's, so the spend of scoring reads on its own.
AI_JUDGE_AI_PRODUCT = "signals_anomaly_scoring"

# Model calls start only in this window. With the longest call after it, the judging of one insight ends in
# `JUDGING_TIMEOUT`, which the insight activity's timeout includes.
JUDGING_START_WINDOW = datetime.timedelta(seconds=60)
JUDGING_TIMEOUT = JUDGING_START_WINDOW + datetime.timedelta(seconds=MAX_JUDGE_CALL_SECONDS)

# A daily key lives past its UTC day, so a call at the end of the day still reads it.
_DAILY_KEY_TTL = datetime.timedelta(days=2)


@frozen
class JudgeCounts:
    # Calls that returned a verdict, and how many of those rejected the z-score flag.
    made: int = 0
    rejected: int = 0
    # Flagged buckets with no call, because of a cap or the time window.
    skipped: int = 0
    # Calls with no verdict: no consent, no credits, a model error, or too short a series.
    failed: int = 0
    # Fetches of the judge's history by a score step. Each one sends the queries of the pick again.
    history_fetches: int = 0


NO_AI_CHECKS = JudgeCounts()


def _daily_key(team_id: int, now: datetime.datetime) -> str:
    return f"signals:anomaly_scoring:ai_checks:{now.astimezone(datetime.UTC).date().isoformat()}:{team_id}"


def reserve_daily_checks(key: str, wanted: int, cap: int) -> int:
    """Reserve up to ``wanted`` model calls of the daily cap at ``key``, and return how many it got."""
    if wanted <= 0:
        return 0
    # `add` sets the key only when it is missing, so two picks of one project never reset each other's count.
    cache.add(key, 0, timeout=int(_DAILY_KEY_TTL.total_seconds()))
    spent = cache.incr(key, wanted)
    over = min(wanted, max(0, spent - cap))
    if over:
        cache.decr(key, over)
    return wanted - over


def release_daily_checks(key: str, unused: int) -> None:
    if unused > 0:
        cache.decr(key, unused)


def _series_label(series: ScoredSeries) -> str:
    if series.breakdown_value is None or series.breakdown_value == series.label:
        return series.label
    return f"{series.label} - {series.breakdown_value}"


def _with_members(point: ScoredPoint, local_type: str, judge: JudgeMemberResult) -> ScoredPoint:
    local = {
        "type": local_type,
        "state": MemberState.FIRED.value if point.flag else MemberState.NOT_FIRED.value,
        "score": point.score,
    }
    return dataclasses.replace(
        point,
        flag=combined_flag(bool(point.flag), judge),
        details={**point.details, "members": [local, judge.details()]},
    )


class _Judging:
    """One insight's judging pass, and the counts of its model calls."""

    def __init__(
        self,
        scores: InsightScores,
        *,
        judge_config: dict[str, Any],
        local_type: str,
        team: Team,
        insight: Insight,
        allowed: set[tuple[str, datetime.datetime]],
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self.scores = scores
        self.judge_config = judge_config
        self.local_type = local_type
        self.team = team
        self.insight = insight
        self.allowed = allowed
        self.deadline = deadline
        self.clock = clock
        self.lines = {line.series_key: line for line in scores.fetched}
        self.calls = 0
        self.made = 0
        self.rejected = 0
        self.skipped = 0
        self.failed = 0

    def series(self, series: ScoredSeries) -> ScoredSeries:
        line = self.lines.get(series.series_key)
        positions = {bucket: index for index, bucket in enumerate(line.buckets)} if line else {}
        # Older buckets go first, so a bucket the judge confirmed is an earlier flag for the newer ones.
        earlier: list[EarlierFlag] = []
        points: list[ScoredPoint] = []
        # Trends can return one bucket start twice, such as the repeated hour at a DST fall-back. The repeat
        # reuses the first result, so one bucket never makes a second model call.
        judged: dict[datetime.datetime, JudgeMemberResult] = {}
        for point in series.points:
            if point.flag is None:
                points.append(point)
                continue
            if point.bucket_start in judged:
                points.append(_with_members(point, self.local_type, judged[point.bucket_start]))
                continue
            result = self._member(series, point, line, positions.get(point.bucket_start), tuple(earlier))
            judged[point.bucket_start] = result
            if result.state == MemberState.FIRED and result.judgment is not None:
                earlier.append(EarlierFlag(date=point.bucket_start.isoformat(), rationale=result.judgment.rationale))
            points.append(_with_members(point, self.local_type, result))
        return dataclasses.replace(series, points=points)

    def _member(
        self,
        series: ScoredSeries,
        point: ScoredPoint,
        line: FetchedSeries | None,
        position: int | None,
        earlier: tuple[EarlierFlag, ...],
    ) -> JudgeMemberResult:
        if not point.flag:
            return not_evaluated(NotEvaluatedReason.LOCAL_NOT_FIRED)
        if (series.series_key, point.bucket_start) not in self.allowed:
            self.skipped += 1
            return not_evaluated(NotEvaluatedReason.CAP)
        if self.clock() >= self.deadline:
            self.skipped += 1
            return not_evaluated(NotEvaluatedReason.TIME_BUDGET)
        if line is None or position is None:
            self.failed += 1
            return not_evaluated(NotEvaluatedReason.TOO_SHORT)
        result = judge_flagged_bucket(
            self.judge_config,
            np.array(line.values[: position + 1], dtype=float),
            series=self._context(series, line, position, earlier),
            team=self.team,
            evaluation_id=(
                f"anomaly_scoring:{self.team.id}:{series.series_key}:{self.scores.detector_version}:"
                f"{point.bucket_start.astimezone(datetime.UTC).isoformat()}"
            ),
            ai_product=AI_JUDGE_AI_PRODUCT,
        )
        # A refused call reached no model, so it gives its place in the daily cap back.
        if result.reason not in (NotEvaluatedReason.PAUSED, NotEvaluatedReason.TOO_SHORT):
            self.calls += 1
        if result.state == MemberState.NOT_EVALUATED:
            self.failed += 1
        else:
            self.made += 1
            self.rejected += result.state == MemberState.NOT_FIRED
        return result

    def _context(
        self, series: ScoredSeries, line: FetchedSeries, position: int, earlier: tuple[EarlierFlag, ...]
    ) -> SeriesContext:
        interval = self.scores.interval.value
        dates = tuple(bucket.isoformat() for bucket in line.buckets[: position + 1])
        shown = dates[-llm_detector_lookback(interval) :]
        description = (
            describe_metric_definition(
                self.insight.query,
                series_index=line.series_index,
                effective_date_range=MetricDateRange(start=shown[0], end=shown[-1]),
            )
            if self.insight.query
            else ""
        )
        return SeriesContext(
            dates=dates,
            interval=interval,
            series_label=_series_label(series),
            metric_description=description,
            insight_name=self.insight.name or "",
            earlier_flags=earlier,
        )

    def counts(self, history_fetches: int) -> JudgeCounts:
        return JudgeCounts(
            made=self.made,
            rejected=self.rejected,
            skipped=self.skipped,
            failed=self.failed,
            history_fetches=history_fetches,
        )


def judge_flags(
    scores: InsightScores,
    *,
    team: Team,
    insight: Insight,
    ai_judge: AIJudgeConfig,
    limits: ScoringLimits = DEFAULT_LIMITS,
    before_history_fetch: Callable[[], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[InsightScores, JudgeCounts]:
    """Add the AI member's result to every scored bucket of a profile with an AI member.

    Never raises for a model error. A failed fetch of the judge's history raises, as a failed scoring fetch does.
    ``before_history_fetch`` runs before that fetch starts, so the caller can charge queries that a failed fetch
    has already sent.
    """
    member = scores.ai_member
    if member is None or member.judge is None:
        return scores, NO_AI_CHECKS
    flagged = sorted(
        {(point.bucket_start, series.series_key) for series in scores.series for point in series.points if point.flag},
        reverse=True,
    )
    # The newest flagged buckets get the calls that both caps allow.
    wanted = flagged[: ai_judge.max_checks_per_insight_per_run]
    # The day of the calls, not of the activity start: a scoring query can end after UTC midnight.
    daily_key = _daily_key(team.id, timezone.now())
    reserved = reserve_daily_checks(daily_key, len(wanted), ai_judge.max_checks_per_project_per_day)
    allowed = {(series_key, bucket_start) for bucket_start, series_key in wanted[:reserved]}
    history_fetches = 0
    # Without consent the judge refuses every call, so the history would be fetched for nothing.
    if reserved and scores.judge_history is not None and team.organization.is_ai_data_processing_approved is True:
        if before_history_fetch is not None:
            before_history_fetch()
        try:
            scores = fetch_judge_history(insight, team, scores, limits)
        except Exception:
            release_daily_checks(daily_key, reserved)
            raise
        history_fetches = 1
    judging = _Judging(
        scores,
        judge_config=member.judge,
        local_type=str(member.local.get("type")),
        team=team,
        insight=insight,
        allowed=allowed,
        deadline=clock() + JUDGING_START_WINDOW.total_seconds(),
        clock=clock,
    )
    try:
        judged = dataclasses.replace(scores, series=[judging.series(series) for series in scores.series])
    finally:
        release_daily_checks(daily_key, reserved - judging.calls)
    counts = judging.counts(history_fetches)
    logger.info(
        "anomaly_scoring_ai_judged",
        team_id=team.id,
        insight_id=insight.id,
        flagged=len(flagged),
        made=counts.made,
        rejected=counts.rejected,
        skipped=counts.skipped,
        failed=counts.failed,
        history_fetches=counts.history_fetches,
    )
    return judged, counts
