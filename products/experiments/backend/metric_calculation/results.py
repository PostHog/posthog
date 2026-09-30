"""Reads of stored metric results.

`MetricResultStore` is the only reader of `ExperimentMetricResult`. Its named queries hide three storage
conventions from the callers:

- A recalculation run files its rows under a salted calculation key (`compute_recalc_fingerprint`), and the daily
  timeseries workflows file theirs under the bare key. So the two families never find each other's rows.
- The timeseries sync copies daily points into a run one second past the newest point (`sync_copy_window`).
- Every writer stores the experiment's start date in `query_from`. After a relaunch moves the start date forward,
  the rows of the earlier run have a `query_from` before it.

Several rows can share `(experiment, metric_uuid, query_to)` once the unique constraint on that key goes. Every
query that can meet such rows returns the one with the newest `completed_at`, then the highest id. It never looks a
row up with `.get()` on that key. While the constraint holds, no two rows tie, so this order changes no result.

Every query filters on the experiment first, so the `(experiment, metric_uuid, query_to)` indexes serve it.
"""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import F, QuerySet
from django.db.models.fields.json import KT, KeyTransform

from posthog.dataclasses import frozen

from products.experiments.backend.metric_calculation.spec import CalculationSpec, plan
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)

# Constant salt: keeps recalc rows distinct from the timeseries workflow's bare config fingerprint, while
# staying deterministic per config so a re-run updates the existing row instead of colliding on the unique key.
_RECALCULATION_SALT = "recalculation"

# The copies land one second past the newest point. A copy at a point's own query_to would share its
# (experiment, metric_uuid, query_to) key with the timeseries row and rewrite that row's fingerprint.
_SYNC_COPY_OFFSET = timedelta(seconds=1)

_COMPLETED = ExperimentMetricResult.Status.COMPLETED


def compute_recalc_fingerprint(config_fingerprint: str) -> str:
    """Fingerprint stamped onto ExperimentMetricResult rows written by the recalculation workflow.

    Returns a 64-char SHA256 hex digest derived solely from the config fingerprint plus a fixed salt, so it is
    deterministic for a given config and deliberately distinct from the timeseries workflow's bare config
    fingerprint.
    """
    return hashlib.sha256(f"{config_fingerprint}{_RECALCULATION_SALT}".encode()).hexdigest()


def _newest_write_first(rows: QuerySet[ExperimentMetricResult], *window_order: str) -> QuerySet[ExperimentMetricResult]:
    """Order `rows` by `window_order`, then put the newest write first among rows that tie on it."""
    return rows.order_by(*window_order, F("completed_at").desc(nulls_last=True), F("id").desc())


@frozen
class DailyTimeseries:
    """The stored results of one metric under one calculation key, one row per day."""

    by_day: dict[date, ExperimentMetricResult]
    earliest: ExperimentMetricResult | None
    latest: ExperimentMetricResult | None


@frozen
class ResultSummary:
    """The fields of a stored result that describe an experiment's outcome. The rest of the result stays in
    Postgres."""

    completed_at: datetime | None
    query_to: datetime
    # The stored JSON values as text, None when the result does not store them.
    baseline_samples: str | None
    baseline_sum: str | None
    variant_results: tuple[dict[str, Any], ...]


@frozen
class MetricResultStore:
    """The stored metric results of one experiment."""

    experiment_id: int

    def for_run(self, run: ExperimentMetricsRecalculation) -> list[ExperimentMetricResult]:
        """The rows of a recalculation run, one per metric uuid, ordered by metric uuid.

        A run has no link to its rows. The rows are found by the salted keys of the run's metrics under the
        current configuration of the experiment, at the run's query_to. A metric that no longer resolves on the
        experiment has no key, so its row is not found. A configuration change after the run changes the keys, so
        the run's rows are not found until the configuration changes back.
        """
        if run.query_to is None:
            return []
        specs = {spec.metric_id: spec for spec in plan(run.experiment)}
        fingerprints = [
            compute_recalc_fingerprint(specs[metric_uuid].calculation_key())
            for metric_uuid in run.metric_uuids or []
            if metric_uuid in specs
        ]
        if not fingerprints:
            return []
        # The recalc fingerprint is deterministic per config, not per run, so a running experiment accumulates one
        # row per query_to under the same fingerprint. Without the query_to filter a later run would return every
        # earlier window's row and overcount.
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id, fingerprint__in=fingerprints, query_to=run.query_to
        )
        return list(_newest_write_first(rows, "metric_uuid").distinct("metric_uuid"))

    def has_completed(self, spec: CalculationSpec, *, window: datetime) -> bool:
        """Whether a recalculation already stored a completed result for this spec at this window."""
        return ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=spec.metric_id,
            query_to=window,
            fingerprint=compute_recalc_fingerprint(spec.calculation_key()),
            status=_COMPLETED,
        ).exists()

    def latest_daily_point(
        self, spec: CalculationSpec, *, since: datetime, until: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point of this spec with the latest query_to inside [since, until]."""
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=spec.metric_id,
            fingerprint=spec.calculation_key(),
            status=_COMPLETED,
            query_to__gte=since,
            query_to__lte=until,
        )
        return _newest_write_first(rows, "-query_to").first()

    def timeseries(self, metric_uuid: str, calculation_key: str, *, timezone: ZoneInfo) -> DailyTimeseries:
        """The rows of one metric under a calculation key, whatever their status, one per day of `timezone`.

        Only daily rows carry the bare key, because a recalculation salts it. The latest query_to inside a day
        stands for that day.
        """
        rows = list(
            _newest_write_first(
                ExperimentMetricResult.objects.filter(
                    experiment_id=self.experiment_id, metric_uuid=metric_uuid, fingerprint=calculation_key
                ),
                "-query_to",
            )
        )
        by_day: dict[date, ExperimentMetricResult] = {}
        for row in rows:
            # A daily row's query_to is the exclusive end of its day, so the microsecond before it falls inside
            # the day the row covers.
            day = (row.query_to - timedelta(microseconds=1)).astimezone(timezone).date()
            by_day.setdefault(day, row)
        return DailyTimeseries(by_day=by_day, earliest=rows[-1] if rows else None, latest=rows[0] if rows else None)

    def last_completed(self, metric_uuid: str) -> ExperimentMetricResult | None:
        """The completed row of a metric that was written last, whatever its configuration and window."""
        return (
            ExperimentMetricResult.objects.filter(
                experiment_id=self.experiment_id, metric_uuid=metric_uuid, status=_COMPLETED
            )
            # NULLS FIRST is the Postgres default for a descending order, so the stop-experiment check keeps its rule.
            # Every writer sets completed_at on a completed row, so NULLS LAST would differ only for rows that no
            # writer creates.
            .order_by(F("completed_at").desc(nulls_first=True), "-id")
            .first()
        )

    def previous_completed(
        self, metric_uuid: str, calculation_key: str, *, before: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point under this key with the latest query_to before `before`."""
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=calculation_key,
            status=_COMPLETED,
            query_to__lt=before,
        )
        return _newest_write_first(rows, "-query_to").first()

    def metric_uuids_stored_at(self, window: datetime, metric_uuids: Iterable[str]) -> set[str]:
        """The metric uuids among `metric_uuids` that have a row at exactly this window, in any status."""
        return set(
            ExperimentMetricResult.objects.filter(
                experiment_id=self.experiment_id, query_to=window, metric_uuid__in=list(metric_uuids)
            ).values_list("metric_uuid", flat=True)
        )

    @staticmethod
    def sync_copy_window(newest_point: datetime) -> datetime:
        """The query_to of a timeseries sync run and of the copies it holds, for daily points up to `newest_point`."""
        return newest_point + _SYNC_COPY_OFFSET

    @staticmethod
    def current_outcomes(metric_uuid_by_experiment: Mapping[int, str]) -> dict[int, ResultSummary]:
        """For each experiment, the completed result of the given metric that describes the current run, in one
        query.

        The current run is the one since the experiment's start date, so rows from before a relaunch do not count.
        Within the run, the row with the latest query_to counts, because a backfill stores a historical query_to
        with completed_at set to the time of the backfill.
        """
        if not metric_uuid_by_experiment:
            return {}
        rows = (
            ExperimentMetricResult.objects.filter(
                experiment_id__in=metric_uuid_by_experiment.keys(),
                metric_uuid__in=set(metric_uuid_by_experiment.values()),
                status=_COMPLETED,
                # `gte` rather than an exact match, so a start date edited to an earlier moment keeps its results
                # instead of hiding them until every row is recomputed. A draft has no start date, so nothing
                # matches.
                query_from__gte=F("experiment__start_date"),
            )
            .order_by("experiment_id", "metric_uuid", "-query_to", F("completed_at").desc(nulls_last=True), "-id")
            .distinct("experiment_id", "metric_uuid")
            .values(
                "experiment_id",
                "metric_uuid",
                "completed_at",
                "query_to",
                baseline_samples=KT("result__baseline__number_of_samples"),
                baseline_sum=KT("result__baseline__sum"),
                variant_results=KeyTransform("variant_results", "result"),
            )
        )
        summaries: dict[int, ResultSummary] = {}
        for row in rows:
            if metric_uuid_by_experiment.get(row["experiment_id"]) != row["metric_uuid"]:
                continue
            variant_results = row["variant_results"] if isinstance(row["variant_results"], list) else []
            summaries[row["experiment_id"]] = ResultSummary(
                completed_at=row["completed_at"],
                query_to=row["query_to"],
                baseline_samples=row["baseline_samples"],
                baseline_sum=row["baseline_sum"],
                variant_results=tuple(variant for variant in variant_results if isinstance(variant, dict)),
            )
        return summaries


def previous_completed_metric_result(
    experiment_id: int, *, team_id: int, metric_uuid: str, calculation_key: str, before: datetime
) -> dict[str, Any] | None:
    """The stored result of the completed daily point under this key with the latest query_to before `before`,
    for callers outside the product. None when there is no such point or the experiment is not in the team."""
    if not Experiment.objects.filter(id=experiment_id, team_id=team_id).exists():
        return None
    row = MetricResultStore(experiment_id=experiment_id).previous_completed(metric_uuid, calculation_key, before=before)
    return row.result if row is not None else None
