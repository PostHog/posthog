"""Index a precomputed metric's filled days as lazy computation jobs.

The lazy computation framework tracks precomputed data as `PreaggregationJob` rows: one per query and UTC day,
with a TTL that decides when the day is rebuilt. Precomputed metrics will move their values into that framework.
Until then their values stay in `MetricPrecomputedChunk`, and this module only registers the days the fill loop
has already stored, so job identity, windows and rebuild cadence run in production before any read depends on them.
Nothing reads these jobs.
"""

import time
import datetime as dt

from django.db.models import Q
from django.utils import timezone

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationExecutor,
    LazyComputationQuery,
    LazyComputationTable,
    compute_query_hash,
    parse_ttl_schedule,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.metrics.backend.facade.enums import PrecomputedMetricKind
from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric

logger = structlog.get_logger(__name__)

DAY = dt.timedelta(days=1)
# The kinds Snuffle fills. The others carry series fingerprints and per-bucket lists, which the shared
# one-value-per-series table can't hold, so they stay on Postgres.
INDEXED_KINDS = frozenset({PrecomputedMetricKind.SUM_OVER_TIME, PrecomputedMetricKind.BUCKET_INCREASE})
# Where the values of an indexed day live. A read that moves to ClickHouse changes this, so jobs registered
# for Postgres-held values are never served as ClickHouse rows.
VALUES_STORE = "postgres_chunks"
RECENT_TTL_SECONDS = 60 * 60
SETTLED_TTL_SECONDS = 7 * 24 * 60 * 60
SETTLED_TTL_JITTER_SECONDS = 2 * 24 * 60 * 60
# The executor's default waits for other builders. The fill pass holds a per-team lock, so it is the only
# builder, and an index pass should never block it for long.
_WAIT_TIMEOUT_SECONDS = 30


def job_query(precomputed_metric: MetricPrecomputedMetric) -> LazyComputationQuery:
    """The job identity of a precomputed metric.

    The executor hashes a HogQL query, but these values come from Snuffle, so the query is a fixed placeholder
    and the definition goes in `cache_key_context`. Buckets are UTC hours, so the timezone is always UTC.
    """
    return LazyComputationQuery(
        query=ast.SelectQuery(select=[ast.Constant(value="metrics_precompute")]),
        table=LazyComputationTable.PREAGGREGATION_RESULTS,
        timezone="UTC",
        cache_key_context={
            "product": "metrics_precompute",
            "values": VALUES_STORE,
            "metric_name": precomputed_metric.metric_name,
            "metric_type": precomputed_metric.metric_type,
            "kind": precomputed_metric.kind,
            "labels": precomputed_metric.labels_key,
            "bucket_seconds": str(precomputed_metric.bucket_seconds),
        },
    )


def job_query_hash(precomputed_metric: MetricPrecomputedMetric) -> str:
    return compute_query_hash(job_query(precomputed_metric))


def _executor(settling_period: dt.timedelta, wait_timeout_seconds: float) -> LazyComputationExecutor:
    # Built per call: the rule cutoffs are relative to now.
    return LazyComputationExecutor(
        wait_timeout_seconds=wait_timeout_seconds,
        ttl_schedule=parse_ttl_schedule(
            {"1d": RECENT_TTL_SECONDS, "default": SETTLED_TTL_SECONDS},
            settling_period_seconds=int(settling_period.total_seconds()),
            default_ttl_jitter_seconds=SETTLED_TTL_JITTER_SECONDS,
            # Without the cap, adjacent settled days with the same TTL merge into one job and rebuild together.
            max_window_days=1,
        ),
    )


@frozen
class _DayRange:
    start: dt.datetime
    end: dt.datetime


def _whole_days(start: dt.datetime, end: dt.datetime) -> _DayRange | None:
    first = dt.datetime.combine(start.astimezone(dt.UTC).date(), dt.time(), tzinfo=dt.UTC)
    if first < start:
        first += DAY
    last = dt.datetime.combine(end.astimezone(dt.UTC).date(), dt.time(), tzinfo=dt.UTC)
    return _DayRange(start=first, end=last) if first < last else None


def index_filled_days(
    team: Team,
    precomputed_metric: MetricPrecomputedMetric,
    settling_period: dt.timedelta,
    wait_timeout_seconds: float = _WAIT_TIMEOUT_SECONDS,
) -> list[PreaggregationJob] | None:
    """Make sure every whole UTC day the metric has stored has a fresh job, and return the jobs that cover them.

    A missing or expired day gets a new job whose build counts the stored buckets of that day. Returns None
    when the metric isn't indexed, has no whole stored day, or the executor didn't finish. A day built before
    `settling_period` has passed since its end is rebuilt once it has, as late samples can still change it.
    Jobs the returned ones replaced are deleted, as the framework has no eviction and nothing reads them.
    """
    if precomputed_metric.kind not in INDEXED_KINDS:
        return None
    if precomputed_metric.covered_from is None or precomputed_metric.covered_to is None:
        return None
    days = _whole_days(precomputed_metric.covered_from, precomputed_metric.covered_to)
    if days is None:
        return None

    def count_stored_buckets(_team: Team, job: PreaggregationJob) -> int:
        return (
            MetricPrecomputedChunk.objects.for_team(team.pk)
            .filter(
                precomputed_metric=precomputed_metric,
                start__gte=job.time_range_start,
                start__lt=job.time_range_end,
            )
            .count()
        )

    query = job_query(precomputed_metric)
    result = _executor(settling_period, wait_timeout_seconds).execute(
        team, query, days.start, days.end, run_insert=count_stored_buckets
    )
    if not result.ready:
        logger.warning(
            "metrics_precompute_index_not_ready",
            precomputed_metric_id=str(precomputed_metric.pk),
            errors=result.errors,
        )
        return None
    PreaggregationJob.objects.filter(team=team, query_hash=compute_query_hash(query)).filter(
        Q(expires_at__lt=timezone.now()) | Q(status=PreaggregationJob.Status.FAILED)
    ).exclude(id__in=result.job_ids).delete()
    return list(PreaggregationJob.objects.filter(team=team, id__in=result.job_ids).order_by("time_range_start"))


def index_team_filled_days(team: Team, settling_period: dt.timedelta, deadline: float) -> None:
    """Index every active metric's stored days until `deadline`, a `time.monotonic()` value.

    A failure is logged and never stops the fill pass. A soft time limit still propagates, so the task's
    `finally` releases the team lock before the worker is killed.
    """
    metrics = MetricPrecomputedMetric.objects.for_team(team.pk).filter(
        state=MetricPrecomputedMetric.State.ACTIVE, kind__in=INDEXED_KINDS
    )
    started = timezone.now()
    for precomputed_metric in metrics:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("metrics_precompute_index_out_of_time", team_id=team.pk)
            break
        try:
            index_filled_days(team, precomputed_metric, settling_period, min(_WAIT_TIMEOUT_SECONDS, remaining))
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("metrics_precompute_index_failed", precomputed_metric_id=str(precomputed_metric.pk))
    logger.info(
        "metrics_precompute_indexed",
        team_id=team.pk,
        duration_ms=round((timezone.now() - started).total_seconds() * 1000),
    )
