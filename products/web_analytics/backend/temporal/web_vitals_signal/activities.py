"""
Temporal activities for the web-vitals signal pipeline.

Three activities:
- `list_opted_in_teams` — find teams that have toggled on either signal source type.
- `evaluate_team_threshold_crossings` — detect band transitions over the last 24h.
- `evaluate_team_regressions` — detect sustained 2h regressions vs a 7d baseline.

Each evaluation activity runs the four-gate emission helper in `posthog.tasks.web_vitals_signal`,
so opt-in / cap / dedup / kill-switch enforcement is shared with the unit-tested layer.
"""

from datetime import timedelta

from django.conf import settings

import structlog
from temporalio import activity

from posthog.models.team.team import Team
from posthog.tasks.web_vitals_signal import (
    REGRESSION_METRICS,
    WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED,
    WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
    WEB_VITALS_THRESHOLDS,
    WebVitalsRegressionSignal,
    WebVitalsSignal,
    WebVitalsThresholdCrossingSignal,
    classify_band,
    enqueue_web_vitals_signals,
    get_last_band,
    increment_regression_streak,
    reset_regression_streak,
    set_last_band,
)

from products.signals.backend.models import SignalSourceConfig
from products.web_analytics.backend.temporal.web_vitals_signal.queries import get_web_vitals_distribution
from products.web_analytics.backend.temporal.web_vitals_signal.types import (
    WebVitalsEvaluationInput,
    WebVitalsEvaluationResult,
)

logger = structlog.get_logger(__name__)

_BAND_SEVERITY = {"good": 0, "needs_improvements": 1, "poor": 2}

# Baseline volume floor scales with the current-window floor. Plan called for ≥1000 baseline
# samples but we wire it to 5× the runtime gate so operators only tune one knob.
_BASELINE_MIN_SAMPLES_MULTIPLIER = 5


@activity.defn
async def list_opted_in_web_vitals_teams() -> list[int]:
    """Return team IDs with at least one web-vitals signal source enabled."""
    from asgiref.sync import sync_to_async

    return await sync_to_async(_list_opted_in_teams_sync)()


def _list_opted_in_teams_sync() -> list[int]:
    return list(
        SignalSourceConfig.objects.filter(
            source_product=WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
            source_type__in=[
                WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
                WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
            ],
            enabled=True,
        )
        .values_list("team_id", flat=True)
        .distinct()
        .order_by("team_id")
    )


@activity.defn
async def evaluate_team_threshold_crossings(input: WebVitalsEvaluationInput) -> WebVitalsEvaluationResult:
    from asgiref.sync import sync_to_async

    return await sync_to_async(_evaluate_threshold_crossings_sync)(input)


def _evaluate_threshold_crossings_sync(input: WebVitalsEvaluationInput) -> WebVitalsEvaluationResult:
    try:
        team = Team.objects.get(pk=input.team_id)
    except Team.DoesNotExist:
        logger.warning("web_vitals_signal_threshold_team_missing", team_id=input.team_id)
        return WebVitalsEvaluationResult(
            team_id=input.team_id,
            metric_window_buckets_evaluated=0,
            signals_emitted=0,
            signals_dropped=0,
        )

    window_hours = settings.WEB_VITALS_SIGNAL_THRESHOLD_WINDOW_HOURS
    min_samples = settings.WEB_VITALS_SIGNAL_MIN_SAMPLES
    now = input.now
    since = now - timedelta(hours=window_hours)

    signals: list[WebVitalsSignal] = []
    buckets_seen = 0

    for metric in WEB_VITALS_THRESHOLDS.keys():
        try:
            buckets = get_web_vitals_distribution(
                team=team,
                metric=metric,
                since=since,
                until=now,
                min_samples=min_samples,
            )
        except Exception:
            logger.exception(
                "web_vitals_signal_threshold_query_failed",
                team_id=input.team_id,
                metric=metric,
            )
            continue

        buckets_seen += len(buckets)
        for bucket in buckets:
            new_band = classify_band(metric, bucket.p75_value)
            previous_band = get_last_band(team.id, metric, bucket.route, bucket.device_class)

            # Always refresh the recorded band so the next evaluation has accurate state.
            set_last_band(team.id, metric, bucket.route, bucket.device_class, new_band)

            if previous_band is None:
                # First observation — establish baseline only.
                continue
            if new_band == previous_band:
                continue
            if _BAND_SEVERITY[new_band] <= _BAND_SEVERITY[previous_band]:
                # Recovery transition — record the new band, but don't emit a signal.
                continue

            signals.append(
                WebVitalsThresholdCrossingSignal(
                    metric=metric,
                    route=bucket.route,
                    device_class=bucket.device_class,
                    p75_value=bucket.p75_value,
                    threshold_band=new_band,
                    previous_band=previous_band,
                    sample_count=bucket.sample_count,
                    window_hours=window_hours,
                )
            )

    emitted = enqueue_web_vitals_signals(team.id, signals) if signals else 0
    dropped = len(signals) - emitted
    logger.info(
        "web_vitals_signal_threshold_evaluated",
        team_id=team.id,
        buckets_evaluated=buckets_seen,
        signals_emitted=emitted,
        signals_dropped=dropped,
    )
    return WebVitalsEvaluationResult(
        team_id=team.id,
        metric_window_buckets_evaluated=buckets_seen,
        signals_emitted=emitted,
        signals_dropped=dropped,
    )


@activity.defn
async def evaluate_team_regressions(input: WebVitalsEvaluationInput) -> WebVitalsEvaluationResult:
    from asgiref.sync import sync_to_async

    return await sync_to_async(_evaluate_regressions_sync)(input)


def _evaluate_regressions_sync(input: WebVitalsEvaluationInput) -> WebVitalsEvaluationResult:
    try:
        team = Team.objects.get(pk=input.team_id)
    except Team.DoesNotExist:
        logger.warning("web_vitals_signal_regression_team_missing", team_id=input.team_id)
        return WebVitalsEvaluationResult(
            team_id=input.team_id,
            metric_window_buckets_evaluated=0,
            signals_emitted=0,
            signals_dropped=0,
        )

    window_hours = settings.WEB_VITALS_SIGNAL_REGRESSION_WINDOW_HOURS
    baseline_days = settings.WEB_VITALS_SIGNAL_BASELINE_WINDOW_DAYS
    min_samples = settings.WEB_VITALS_SIGNAL_MIN_SAMPLES
    baseline_min_samples = min_samples * _BASELINE_MIN_SAMPLES_MULTIPLIER
    pct_threshold = float(settings.WEB_VITALS_SIGNAL_REGRESSION_PCT_THRESHOLD)
    abs_threshold = float(settings.WEB_VITALS_SIGNAL_REGRESSION_ABS_THRESHOLD_MS)

    now = input.now
    current_since = now - timedelta(hours=window_hours)
    # Baseline = trailing `baseline_days` ending 1 day ago, to avoid contaminating the
    # baseline with the current window itself or its immediate lead-up.
    baseline_until = now - timedelta(days=1)
    baseline_since = baseline_until - timedelta(days=baseline_days)

    signals: list[WebVitalsSignal] = []
    buckets_seen = 0

    for metric in REGRESSION_METRICS:
        try:
            current_buckets = get_web_vitals_distribution(
                team=team,
                metric=metric,
                since=current_since,
                until=now,
                min_samples=min_samples,
            )
            baseline_buckets = get_web_vitals_distribution(
                team=team,
                metric=metric,
                since=baseline_since,
                until=baseline_until,
                min_samples=baseline_min_samples,
            )
        except Exception:
            logger.exception(
                "web_vitals_signal_regression_query_failed",
                team_id=input.team_id,
                metric=metric,
            )
            continue

        baseline_map = {(b.route, b.device_class): b for b in baseline_buckets}
        buckets_seen += len(current_buckets)

        for current in current_buckets:
            key = (current.route, current.device_class)
            baseline = baseline_map.get(key)
            if baseline is None or baseline.p75_value <= 0:
                # No baseline to compare against (new route, low volume, etc.) — reset
                # any in-flight streak so a future baseline doesn't trigger off stale state.
                reset_regression_streak(team.id, metric, current.route, current.device_class)
                continue

            delta = current.p75_value - baseline.p75_value
            pct = (delta / baseline.p75_value) * 100.0
            is_regressing = pct >= pct_threshold and delta >= abs_threshold

            if not is_regressing:
                reset_regression_streak(team.id, metric, current.route, current.device_class)
                continue

            streak = increment_regression_streak(team.id, metric, current.route, current.device_class)
            if streak < WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED:
                continue

            signals.append(
                WebVitalsRegressionSignal(
                    metric=metric,
                    route=current.route,
                    device_class=current.device_class,
                    current_p75=current.p75_value,
                    baseline_p75=baseline.p75_value,
                    sample_count=current.sample_count,
                    baseline_sample_count=baseline.sample_count,
                    window_hours=window_hours,
                    baseline_window_days=baseline_days,
                )
            )

    emitted = enqueue_web_vitals_signals(team.id, signals) if signals else 0
    dropped = len(signals) - emitted
    logger.info(
        "web_vitals_signal_regression_evaluated",
        team_id=team.id,
        buckets_evaluated=buckets_seen,
        signals_emitted=emitted,
        signals_dropped=dropped,
    )
    return WebVitalsEvaluationResult(
        team_id=team.id,
        metric_window_buckets_evaluated=buckets_seen,
        signals_emitted=emitted,
        signals_dropped=dropped,
    )
