import json
import math
import hashlib
import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import structlog

from posthog.schema import BreakdownFilter, ChartDisplayType, DateRange, IntervalType, TrendsQuery

from posthog.hogql.constants import INSIGHT_QUERY_FANOUT_CONCURRENCY, HogQLGlobalSettings, LimitContext

from posthog.api.services.query import ExecutionMode
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, get_team_query_tags, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.hogql_queries.utils.breakdowns import has_breakdown_filter
from posthog.hogql_queries.validation.rules import expanded_series_count
from posthog.interval_specs import interval_spec
from posthog.models import Team
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionResult, DetectorArtifact, FitError
from posthog.tasks.alerts.detectors.registry import get_detector
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, is_non_time_series_trend

from products.product_analytics.backend.facade.models import Insight
from products.product_analytics.backend.facade.queries import TrendsQueryRunner
from products.signals.backend.anomaly_scores.artifacts import model_id_of
from products.signals.backend.anomaly_scores.config import (
    DEFAULT_LIMITS,
    IntervalScoring,
    ScoringLimits,
    ScoringProfile,
    ScoringRun,
    resolve_profile,
)

logger = structlog.get_logger(__name__)

# Naming fields do not change what a series counts, so a rename keeps its key.
_SERIES_NAMING_FIELDS = {"custom_name", "name"}

_MAX_SMOOTHING_BUCKETS = 90

_DATE_UNITS = {IntervalType.HOUR: "h", IntervalType.DAY: "d", IntervalType.WEEK: "w", IntervalType.MONTH: "m"}

# The scoring query runs as background work, so it gets more time than a chart query and fewer threads.
_MAX_QUERY_SECONDS = 150
# Trends runs one query per series in a pool of INSIGHT_QUERY_FANOUT_CONCURRENCY threads, so more series run in waves.
# All the waves of one insight share this budget. The insight activity then has time to classify a timeout.
SCORING_QUERY_BUDGET_SECONDS = 210


class UnsupportedInsightError(Exception):
    """The insight is not a shape we score. The caller skips it; it is not an error."""


@frozen
class ScoredPoint:
    bucket_start: datetime
    value: float
    # Both are None during warm-up, so an average of the flag stays a true anomaly rate.
    score: float | None
    flag: bool | None
    details: dict[str, Any]


@frozen
class ScoredSeries:
    series_key: str
    label: str
    breakdown_value: str | None
    points: list[ScoredPoint]


@frozen
class StateIdentity:
    """What a stored state was built from. A score step needs the same identity, or the visit trains."""

    interval: IntervalType
    detector_version: str
    query_hash: str


@frozen
class TrainedState:
    identity: StateIdentity
    trained_at: datetime
    # The newest scored bucket start over all series, or None when no series had a completed bucket.
    scored_through: datetime | None
    # The series that the stored artifact blob covers.
    series_keys: tuple[str, ...]
    # Empty until the blob of a train step is written.
    artifact_key: str = ""
    artifact_sha256: str = ""
    # Stored series that the last score step did not get back.
    missing_series: int = 0


@frozen
class SplitRun:
    """A visit of the train and score split. A score step needs ``state`` and its ``artifacts``, or the visit trains."""

    state: TrainedState | None = None
    # Series key to the artifact of the stored blob of ``state``.
    artifacts: dict[str, DetectorArtifact] | None = None


@frozen
class InsightScores:
    interval: IntervalType
    profile: str
    detector: str
    detector_version: str
    series: list[ScoredSeries]
    # None when the split is off. Then no state is stored.
    run: ScoringRun | None = None
    # The state for the next visit to store.
    state: TrainedState | None = None
    # The artifacts that a train step fit, for the caller to store. None on a score step.
    artifacts: dict[str, DetectorArtifact] | None = None
    # Series of a score step with no stored artifact. A later train step fits them.
    unmatched_series: int = 0
    # The artifact blob that scored the buckets. None when the split is off.
    model_id: str | None = None


@frozen
class _FetchedSeries:
    series_key: str
    label: str
    breakdown_value: str | None
    values: list[float]
    buckets: list[datetime]


def _short_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def detector_version(scoring: IntervalScoring, *, artifacts: bool = False) -> str:
    """Identifies the scoring behavior, so scores from different settings are never mixed in one series.

    Score steps read stored artifacts, so the split gets its own version. Bump it when train-step scores change.
    """
    behavior: dict[str, Any] = {"min_points": scoring.min_points, "detector": scoring.detector}
    if artifacts:
        behavior["fit"] = "artifact_v2"
    return _short_hash(behavior)


def query_hash(query: TrendsQuery, timezone: ZoneInfo, limits: ScoringLimits = DEFAULT_LIMITS) -> str:
    """Identifies what the scoring query counts, without its date range, so an edited insight retrains."""
    dumped = build_scoring_query(query, buckets=1, limits=limits).model_dump(mode="json", exclude_none=True)
    # The fetch size changes with every visit. `daysOfWeek` stays, because it changes the buckets.
    (dumped.get("dateRange") or {}).pop("date_from", None)
    # Bucket starts step in wall-clock time, so a timezone change needs new artifacts.
    return _short_hash({"query": dumped, "timezone": timezone.key})


def series_key(insight_id: int, series_definition: dict[str, Any], breakdown_value: str | None) -> str:
    return _short_hash({"insight": insight_id, "series": series_definition, "breakdown": breakdown_value})


def trends_query_for(insight: Insight, profile: ScoringProfile) -> TrendsQuery:
    if insight.query is None:
        raise UnsupportedInsightError("Insight has no query")
    with upgrade_insight(insight):
        query = insight.query
    if query.get("kind") in WRAPPER_NODE_KINDS:
        query = query.get("source") or {}
    if query.get("kind") != "TrendsQuery":
        raise UnsupportedInsightError(f"Only trends insights are scored, not {query.get('kind')}")
    trends = TrendsQuery.model_validate(query)
    if not trends.series:
        raise UnsupportedInsightError("Insight has no series")
    if is_non_time_series_trend(trends):
        raise UnsupportedInsightError("Insight shows a single value, not a time series")
    if trends.trendsFilter and trends.trendsFilter.display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE:
        raise UnsupportedInsightError("Cumulative insights are not scored")
    if trends.trendsFilter and trends.trendsFilter.display == ChartDisplayType.CALENDAR_HEATMAP:
        # The chart has its own runner and shows hours of the week, not a time series.
        raise UnsupportedInsightError("Calendar heatmaps are not scored")
    interval_scoring(profile, scoring_interval(trends))
    return trends


def interval_scoring(profile: ScoringProfile, interval: IntervalType) -> IntervalScoring:
    scoring = profile.for_interval(interval)
    if scoring is None:
        raise UnsupportedInsightError(f"Interval {interval.value} is not scored")
    return scoring


def _detector_history(detector: dict[str, Any]) -> int:
    """Buckets the detector reads to score its newest bucket. A detector without a window reads all it gets."""
    if isinstance(detector.get("detectors"), list):
        return max((_detector_history(sub) for sub in detector["detectors"]), default=0)
    window = detector.get("window")
    if not isinstance(window, int):
        return 0
    preprocessing = detector.get("preprocessing") or {}
    # Differencing and trailing smoothing each read buckets before the first one they output.
    consumed = (
        (1 if preprocessing.get("diffs_n") else 0)
        + max((preprocessing.get("smooth_n") or 0) - 1, 0)
        + (preprocessing.get("lags_n") or 0)
    )
    return window + max(detector.get("training_offset_n", 1), 1) + consumed


def history_buckets(scoring: IntervalScoring) -> int:
    """Completed buckets up to and including a scored bucket that its score depends on."""
    return max(scoring.min_points, _detector_history(scoring.detector))


def buckets_to_score(
    interval: IntervalType,
    *,
    now: datetime,
    after: datetime | None,
    timezone: ZoneInfo,
    limits: ScoringLimits = DEFAULT_LIMITS,
) -> int:
    if after is None:
        return limits.max_backfill_buckets
    count = 0
    start = bucket_end(after.astimezone(timezone), interval)
    while count < limits.max_backfill_buckets and bucket_end(start, interval) <= now:
        count += 1
        start = bucket_end(start, interval)
    return max(count, 1)


def fetch_buckets(query: TrendsQuery, scoring: IntervalScoring, to_score: int, *, history: int | None = None) -> int:
    """Completed buckets the scoring query fetches: the history of the oldest bucket to score, then the rest.

    The count has one bucket more than the scores read, so a first bucket that the date range cuts short is never read.
    ``history`` replaces the detector history, for the train and score steps of the split.
    """
    count = (history_buckets(scoring) if history is None else history) + to_score
    smoothing = query.trendsFilter.smoothingIntervals if query.trendsFilter else None
    if smoothing and smoothing > _MAX_SMOOTHING_BUCKETS:
        # The field has no upper bound, and the fetch grows with it.
        raise UnsupportedInsightError(f"Smoothing over {smoothing} buckets is not scored")
    if smoothing and smoothing > 1:
        # Trends smooths over the fetched buckets only, so the oldest values need their own trailing window.
        count += smoothing - 1
    days_of_week = query.dateRange.daysOfWeek if query.dateRange else None
    if days_of_week and scoring_interval(query) == IntervalType.DAY:
        # Trends drops the buckets of the days that the filter leaves out.
        count = math.ceil(count * 7 / len(set(days_of_week)))
    return count


def build_scoring_query(query: TrendsQuery, buckets: int, limits: ScoringLimits = DEFAULT_LIMITS) -> TrendsQuery:
    """Fetch the newest ``buckets`` completed buckets instead of the chart's date range.

    Series, filters and formulas stay as they are, so the scores describe the series the chart shows.
    """
    days_of_week = query.dateRange.daysOfWeek if query.dateRange else None
    update: dict[str, Any] = {
        "dateRange": DateRange(date_from=f"-{buckets}{_DATE_UNITS[scoring_interval(query)]}", daysOfWeek=days_of_week),
        "compareFilter": None,
    }
    if query.trendsFilter and query.trendsFilter.display == ChartDisplayType.METRIC:
        # The runner adds the previous period for a Metric display. A line display returns the same buckets.
        update["trendsFilter"] = query.trendsFilter.model_copy(update={"display": ChartDisplayType.ACTIONS_LINE_GRAPH})
    if has_breakdown_filter(query.breakdownFilter):
        lines_per_value = len(_formulas(query)) or len(query.series)
        breakdown_filter = query.breakdownFilter or BreakdownFilter()
        # "Other" mixes whichever values fall outside the top N on each run, so it is not one series.
        update["breakdownFilter"] = breakdown_filter.model_copy(
            update={
                "breakdown_limit": max(1, min(limits.max_breakdown_values, limits.max_series // lines_per_value)),
                "breakdown_hide_other_aggregation": True,
            }
        )
    return query.model_copy(update=update)


def scoring_query_settings(queries: int) -> HogQLGlobalSettings:
    """Settings for each of the ``queries`` queries of one insight, so that all of them stop within the shared budget."""
    waves = max(1, math.ceil(queries / INSIGHT_QUERY_FANOUT_CONCURRENCY))
    return HogQLGlobalSettings(
        max_execution_time=min(_MAX_QUERY_SECONDS, SCORING_QUERY_BUDGET_SECONDS // waves),
        max_threads=8,
        # A timeout must throw: a partial result cuts off the end of the series, and that end scores as a drop.
        timeout_overflow_mode="throw",
    )


def supports_score_step(query: TrendsQuery) -> bool:
    """A score step reads the buckets before a scored bucket as its context, so the buckets must have no gaps."""
    # Trends drops the buckets of the days that the filter leaves out.
    return not (query.dateRange and query.dateRange.daysOfWeek)


def state_identity(query: TrendsQuery, scoring: IntervalScoring, team: Team, limits: ScoringLimits) -> StateIdentity:
    return StateIdentity(
        interval=scoring_interval(query),
        detector_version=detector_version(scoring, artifacts=True),
        query_hash=query_hash(query, team.timezone_info, limits),
    )


def query_cost(insight: Insight, team: Team) -> int:
    """The ClickHouse queries that scoring this insight sends, so the tick can budget them before it runs.

    It counts the scoring query the same way as `TrendsQueryRunner`: one query per series, and one per
    cohort for each series of a cohort breakdown.
    """
    try:
        query = build_scoring_query(trends_query_for(insight, resolve_profile(team, insight)), buckets=1)
    except Exception:
        # Scoring builds the same query, so it fails before it sends a query and reports the error itself.
        # One query is the safe charge, and one bad insight cannot stop the tick for every project.
        return 1
    # A team can resolve a cohort breakdown in one query per series. The larger count is the safe charge.
    cohort_breakdown = query.breakdownFilter is not None and query.breakdownFilter.breakdown_type == "cohort"
    return max(1, expanded_series_count(query, cohort_breakdown_expands=cohort_breakdown))


def score_series(
    values: Sequence[float],
    buckets: Sequence[datetime],
    *,
    scoring: IntervalScoring,
    interval: IntervalType,
    now: datetime,
    after: datetime | None = None,
    limits: ScoringLimits = DEFAULT_LIMITS,
) -> list[ScoredPoint]:
    """Score one series and return its newest completed buckets later than ``after``.

    ``buckets`` are aware bucket starts in the project timezone.
    """
    if len(values) != len(buckets):
        raise ValueError("Each value needs a bucket")
    completed = [i for i, start in enumerate(buckets) if bucket_end(start, interval) <= now]
    returned = [i for i in completed if after is None or buckets[i] > after][-limits.max_backfill_buckets :]
    detector = get_detector(scoring.detector)
    data = np.array(values, dtype=float)

    points: list[ScoredPoint] = []
    for i in returned:
        # Score each bucket on the history up to it, so the ongoing bucket and later buckets never shape the score.
        # detect() fits once per call; detect_batch() refits at every point of the lookback for model-based detectors.
        result = detector.detect(data[: i + 1]) if i + 1 >= scoring.min_points else None
        score = None if result is None or result.score is None else float(result.score)
        points.append(
            ScoredPoint(
                bucket_start=buckets[i],
                value=float(values[i]),
                score=score,
                flag=None if result is None or score is None else result.is_anomaly,
                details={} if result is None or score is None else _details(result),
            )
        )
    return points


@frozen
class ScoredIndices:
    completed: list[int]
    # The newest completed buckets later than `after`, capped at `max_backfill_buckets`.
    returned: list[int]


def _scored_indices(
    buckets: Sequence[datetime], *, interval: IntervalType, now: datetime, after: datetime | None, limits: ScoringLimits
) -> ScoredIndices:
    """The indices of the completed buckets, and of the newest of them later than ``after``."""
    completed = [i for i, start in enumerate(buckets) if bucket_end(start, interval) <= now]
    returned = [i for i in completed if after is None or buckets[i] > after][-limits.max_backfill_buckets :]
    return ScoredIndices(completed=completed, returned=returned)


def score_with_artifact(
    detector: BaseDetector,
    artifact: DetectorArtifact | None,
    values: Sequence[float],
    buckets: Sequence[datetime],
    indices: list[int],
) -> list[ScoredPoint]:
    """Score the buckets at ``indices`` with a fitted artifact. A bucket without enough context before it gets no score."""
    context = detector.context_buckets()
    scored = [i for i in indices if i >= context]
    result = None
    if artifact is not None and scored:
        result = detector.score(artifact, np.array(values[scored[0] - context : scored[-1] + 1], dtype=float))
    positions = {i: position for position, i in enumerate(scored)}
    points: list[ScoredPoint] = []
    for i in indices:
        position = positions.get(i)
        score = flag = None
        details: dict[str, Any] = {}
        if result is not None and position is not None and result.all_scores[position] is not None:
            score = float(cast(float, result.all_scores[position]))
            flag = position in result.triggered_indices
            details = _details_of(result.all_metadata[position])
        points.append(
            ScoredPoint(bucket_start=buckets[i], value=float(values[i]), score=score, flag=flag, details=details)
        )
    return points


def _fit(
    detector: BaseDetector, scoring: IntervalScoring, values: Sequence[float], end: int
) -> DetectorArtifact | None:
    """Fit on the buckets before ``end`` that ``detect()`` reads to score ``end``, or None when they are too few."""
    history = np.array(values[max(0, end - (history_buckets(scoring) - 1)) : end], dtype=float)
    # The scored bucket counts toward `min_points`, as in `score_series`.
    if len(history) + 1 < scoring.min_points:
        return None
    try:
        return detector.fit(history)
    except FitError:
        return None


def score_insight(
    insight: Insight,
    team: Team,
    *,
    now: datetime,
    after: datetime | None = None,
    limits: ScoringLimits = DEFAULT_LIMITS,
    split: SplitRun | None = None,
) -> InsightScores:
    """Score the new buckets of an insight.

    With ``split``, a stored state with the insight's identity and its artifacts makes this a score step, and
    anything else a train step. Both return the state for the next visit, and a train step returns the
    artifacts to store.
    """
    profile = resolve_profile(team, insight)
    query = trends_query_for(insight, profile)
    interval = scoring_interval(query)
    scoring = interval_scoring(profile, interval)
    timezone = team.timezone_info
    scores = InsightScores(
        interval=interval,
        profile=profile.name,
        detector=str(scoring.detector["type"]),
        detector_version=detector_version(scoring, artifacts=split is not None),
        series=[],
    )

    if split is None:
        to_score = buckets_to_score(interval, now=now, after=after, timezone=timezone, limits=limits)
        fetched = _fetch(insight, team, query, fetch_buckets(query, scoring, to_score), limits, None)
        series = [
            ScoredSeries(
                series_key=line.series_key,
                label=line.label,
                breakdown_value=line.breakdown_value,
                points=score_series(
                    line.values, line.buckets, scoring=scoring, interval=interval, now=now, after=after, limits=limits
                ),
            )
            for line in fetched
        ]
        return dataclasses.replace(scores, series=series)

    identity = state_identity(query, scoring, team, limits)
    state = split.state
    detector = get_detector(scoring.detector)
    if (
        state is not None
        and split.artifacts is not None
        and state.identity == identity
        and state.scored_through is not None
        and supports_score_step(query)
    ):
        return _score_step(
            insight,
            team,
            query,
            scores,
            state,
            split.artifacts,
            detector,
            scoring=scoring,
            now=now,
            after=after,
            limits=limits,
        )
    return _train_step(
        insight, team, query, scores, identity, detector, scoring=scoring, now=now, after=after, limits=limits
    )


def _train_step(
    insight: Insight,
    team: Team,
    query: TrendsQuery,
    scores: InsightScores,
    identity: StateIdentity,
    detector: BaseDetector,
    *,
    scoring: IntervalScoring,
    now: datetime,
    after: datetime | None,
    limits: ScoringLimits,
) -> InsightScores:
    """Score each due bucket with a fit on the history before it, and store a fit through the newest completed bucket."""
    interval = scores.interval
    to_score = buckets_to_score(interval, now=now, after=after, timezone=team.timezone_info, limits=limits)
    buckets = fetch_buckets(query, scoring, to_score)
    fetched = _fetch(insight, team, query, buckets, limits, ScoringRun.TRAIN)
    series: list[ScoredSeries] = []
    artifacts: dict[str, DetectorArtifact] = {}
    newest: list[datetime] = []
    for line in fetched:
        indices = _scored_indices(line.buckets, interval=interval, now=now, after=after, limits=limits)
        completed, returned = indices.completed, indices.returned
        if completed:
            newest.append(line.buckets[completed[-1]])
        # A refit per due bucket scores a backfill like `score_series`. One fit for all of them goes stale.
        points = [
            point
            for i in returned
            for point in score_with_artifact(
                detector, _fit(detector, scoring, line.values, i), line.values, line.buckets, [i]
            )
        ]
        artifact = _fit(detector, scoring, line.values, completed[-1] + 1) if completed else None
        if artifact is not None:
            artifacts[line.series_key] = artifact
        series.append(
            ScoredSeries(
                series_key=line.series_key,
                label=line.label,
                breakdown_value=line.breakdown_value,
                points=points,
            )
        )
    return dataclasses.replace(
        scores,
        series=series,
        run=ScoringRun.TRAIN,
        artifacts=artifacts,
        state=TrainedState(
            identity=identity,
            trained_at=now,
            scored_through=max(newest).astimezone(UTC) if newest else None,
            series_keys=tuple(artifacts),
        ),
    )


def _score_step(
    insight: Insight,
    team: Team,
    query: TrendsQuery,
    scores: InsightScores,
    state: TrainedState,
    artifacts: dict[str, DetectorArtifact],
    detector: BaseDetector,
    *,
    scoring: IntervalScoring,
    now: datetime,
    after: datetime | None,
    limits: ScoringLimits,
) -> InsightScores:
    """Score the buckets after the older of ``after`` and ``state.scored_through`` with the stored artifacts.

    ``after`` is the oldest newest-scored bucket over the series. A series that missed a visit, for example a
    breakdown value out of the top N, then still gets its missed buckets, and the events drop each series' buckets
    up to its own newest scored bucket. Nothing is fitted.
    """
    interval = scores.interval
    since = min((through for through in (after, state.scored_through) if through is not None), default=None)
    to_score = buckets_to_score(interval, now=now, after=since, timezone=team.timezone_info, limits=limits)
    # One bucket more than the context that preprocessing reads, as in the full fetch.
    buckets = fetch_buckets(query, scoring, to_score, history=detector.context_buckets() + 1)
    fetched = _fetch(insight, team, query, buckets, limits, ScoringRun.SCORE)
    series: list[ScoredSeries] = []
    unmatched = 0
    returned_keys: set[str] = set()
    scored_through = state.scored_through
    for line in fetched:
        returned_keys.add(line.series_key)
        artifact = artifacts.get(line.series_key)
        # The short range can rank a different top N of breakdown values. A new value waits for a train step.
        if artifact is None:
            unmatched += 1
            continue
        returned = _scored_indices(line.buckets, interval=interval, now=now, after=since, limits=limits).returned
        points = score_with_artifact(detector, artifact, line.values, line.buckets, returned)
        if points:
            newest = points[-1].bucket_start.astimezone(UTC)
            scored_through = newest if scored_through is None else max(scored_through, newest)
        series.append(
            ScoredSeries(
                series_key=line.series_key, label=line.label, breakdown_value=line.breakdown_value, points=points
            )
        )
    return dataclasses.replace(
        scores,
        series=series,
        run=ScoringRun.SCORE,
        unmatched_series=unmatched,
        state=dataclasses.replace(
            state, scored_through=scored_through, missing_series=len(set(state.series_keys) - returned_keys)
        ),
        model_id=model_id_of(state.artifact_key),
    )


def _fetch(
    insight: Insight,
    team: Team,
    query: TrendsQuery,
    buckets: int,
    limits: ScoringLimits,
    run: ScoringRun | None,
) -> list[_FetchedSeries]:
    timezone = team.timezone_info
    scoring_query = build_scoring_query(query, buckets, limits)

    tag_queries(**get_team_query_tags(team), insight_id=insight.pk)
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    if run is not None:
        # Splits the scoring queries in `query_log`, so train and score cost can be compared.
        tag_queries(name=f"anomaly_scoring_{run.value}")
    runner = TrendsQueryRunner(
        query=scoring_query,
        team=team,
        # No request user. Run as the insight's creator so warehouse access control resolves for them.
        user=insight.created_by,
        # The async context raises the timeout above scoring_query_settings. One slow insight must not hold a tick.
        limit_context=LimitContext.QUERY,
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.DEFAULT,
    )
    # The runner expands breakdown cohorts and compare periods into the series, so its count is the query count.
    runner.hogql_settings = scoring_query_settings(len(runner.series))
    response = runner.run(
        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        insight_id=insight.pk,
        analytics_props={"source": EventSource.SELF_DRIVING},
    )
    results = getattr(response, "results", None)
    if not isinstance(results, list):
        raise RuntimeError(f"No results for insight {insight.pk}")

    current_results = [
        result for result in cast(list[dict[str, Any]], results) if result.get("compare_label") != "previous"
    ]
    if len(current_results) < len(results):
        # A previous-period line has the key of its current line and old buckets, so it would write a false series.
        logger.warning(
            "anomaly_scores.previous_period_skipped",
            insight_id=insight.pk,
            skipped=len(results) - len(current_results),
        )

    series: list[_FetchedSeries] = []
    key_counts: dict[str, int] = {}
    for result in current_results[: limits.max_series]:
        breakdown_value = _breakdown_label(result.get("breakdown_value"))
        key = series_key(insight.pk, _series_definition(scoring_query, result), breakdown_value)
        repeats = key_counts.get(key, 0)
        key_counts[key] = repeats + 1
        series.append(
            _FetchedSeries(
                # Lines that differ only by name share a key. Event uuids come from the key, so each repeat needs its own.
                series_key=key if repeats == 0 else _short_hash({"key": key, "repeat": repeats}),
                label=str(result.get("label") or ""),
                breakdown_value=breakdown_value,
                values=list(result.get("data") or []),
                buckets=[_parse_bucket(day, timezone) for day in result.get("days") or []],
            )
        )
    return series


def _formulas(query: TrendsQuery) -> list[str]:
    trends_filter = query.trendsFilter
    if trends_filter is None:
        return []
    if trends_filter.formulaNodes:
        return [node.formula for node in trends_filter.formulaNodes]
    if trends_filter.formulas:
        return list(trends_filter.formulas)
    return [trends_filter.formula] if trends_filter.formula else []


def _series_node_definition(node: Any) -> dict[str, Any]:
    return node.model_dump(exclude_none=True, exclude=_SERIES_NAMING_FIELDS)


def _series_definition(query: TrendsQuery, result: dict[str, Any]) -> dict[str, Any]:
    """What a result line counts, independent of where its series sits in the query."""
    formulas = _formulas(query)
    if formulas:
        # A formula refers to series by letter, so its meaning includes every series in order.
        order = result.get("order") or 0
        return {
            "formula": formulas[order] if order < len(formulas) else None,
            "series": [_series_node_definition(node) for node in query.series],
        }
    order = result.get("order")
    if order is None or order >= len(query.series):
        return {"label": result.get("label")}
    return _series_node_definition(query.series[order])


def scoring_interval(query: TrendsQuery) -> IntervalType:
    return query.interval or IntervalType.DAY


def bucket_end(start: datetime, interval: IntervalType) -> datetime:
    if interval == IntervalType.HOUR:
        # An hour is elapsed time, so step in UTC to stay one hour long across DST changes.
        return (start.astimezone(UTC) + timedelta(hours=1)).astimezone(start.tzinfo)
    # Wall-clock arithmetic on an aware datetime, so a day stays one calendar day across DST changes.
    return start + interval_spec(interval).period


def _details(result: DetectionResult) -> dict[str, Any]:
    return _details_of(result.metadata)


def _details_of(metadata: dict[str, Any]) -> dict[str, Any]:
    """Detector-specific values for one bucket. Only scalars are kept, so the event property stays small."""
    sub_results = metadata.get("sub_results")
    if isinstance(sub_results, list):
        return {
            "sub_scores": {
                f"{sub.get('type')}_{position}": sub.get("score") for position, sub in enumerate(sub_results)
            }
        }
    return {key: value for key, value in metadata.items() if value is None or isinstance(value, int | float | str)}


def _parse_bucket(day: str, timezone: ZoneInfo) -> datetime:
    # Trends returns bucket starts in the project's timezone, usually as naive strings.
    parsed = datetime.fromisoformat(day)
    return parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=timezone)


def _breakdown_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "::".join(str(part) for part in value)
    return str(value)
