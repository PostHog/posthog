"""Reads and writes of stored metric results.

`MetricResultStore` is the only module that reads or writes `ExperimentMetricResult`. Its named queries and writes
hide two storage conventions from the callers:

- A recalculation run files its rows under a salted calculation key (`_recalc_fingerprint`), and the daily
  timeseries workflows file theirs under the bare key. So the run reads, the reuse check and the chart never find
  the other family's rows. Only the current outcome reads both, because both hold results of the same calculation.
- The timeseries sync copies daily points into a run one second past the newest point (`sync_copy_window`).

The calculation key includes the start date, so no reader needs `query_from` to tell a relaunch apart.

Several rows can share `(experiment, metric_uuid, query_to)` once the unique constraint on that key goes. Every
query that can meet such rows returns the one with the newest `completed_at`, then the highest id. It never looks a
row up with `.get()` on that key. While the constraint holds, no two rows tie, so this order changes no result.

Every write looks the row up on `(experiment, metric_uuid, query_to)` and stores the fingerprint as an updated
field. A row that holds the window under another fingerprint is therefore updated in place, and no write can
violate the unique constraint or create a second row for a window. A daily failure is the exception: it leaves a
completed row under another fingerprint in place, because it has no result to replace that row with.

Every query filters on the experiment first, so the `(experiment, metric_uuid, query_to)` indexes serve it.
"""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.db.models.fields.json import KT, KeyTransform
from django.db.models.functions import Least
from django.utils import timezone as django_timezone

import structlog

from posthog.schema import ExperimentQueryResponse

from posthog.dataclasses import frozen

from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.logic.result_stats import MetricResultStats, parse_stored_response
from products.experiments.backend.metric_calculation.config import MetricCalculationConfig, build_calculation_configs
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
_FAILED = ExperimentMetricResult.Status.FAILED

_TERMINAL_RECALC_STATUSES = frozenset(
    {ExperimentMetricsRecalculation.Status.COMPLETED, ExperimentMetricsRecalculation.Status.FAILED}
)

logger = structlog.get_logger(__name__)


def _recalc_fingerprint(config_fingerprint: str) -> str:
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

    def for_run(self, run: ExperimentMetricsRecalculation, *, with_result: bool = True) -> list[ExperimentMetricResult]:
        """The rows of a recalculation run, one per metric uuid, ordered by metric uuid. With `with_result=False` the
        rows don't load `result`, which for a funnel holds the sessions of each step, and reading it queries again.

        A run has no link to its rows. The rows are found by the salted keys of the run's metrics under the
        current configuration of the experiment, at the run's query_to. A metric that no longer resolves on the
        experiment has no key, so its row is not found. A configuration change after the run changes the keys, so
        the run's rows are not found until the configuration changes back.
        """
        if run.query_to is None:
            return []
        calculation_configs = {
            calculation_config.metric_id: calculation_config
            for calculation_config in build_calculation_configs(run.experiment)
        }
        fingerprints = [
            _recalc_fingerprint(calculation_configs[metric_uuid].calculation_key())
            for metric_uuid in run.metric_uuids or []
            if metric_uuid in calculation_configs
        ]
        if not fingerprints:
            return []
        # The recalc fingerprint is per config, not per run, so each window of a running experiment holds a row under
        # the same fingerprint. Without the query_to filter a later run would return every earlier window's row.
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id, fingerprint__in=fingerprints, query_to=run.query_to
        )
        if not with_result:
            rows = rows.defer("result")
        return list(_newest_write_first(rows, "metric_uuid").distinct("metric_uuid"))

    def exposures_paths(self, rows: Iterable[ExperimentMetricResult]) -> frozenset[ExposuresPath]:
        """Where the queries of these rows read the exposures. It reads one key of `result`, so the rows of `for_run` can
        leave `result` unloaded. A result without the key adds nothing."""
        stored = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id, pk__in=[row.pk for row in rows]
        ).values_list("result__is_precomputed", flat=True)
        return frozenset(
            ExposuresPath.PRECOMPUTED if is_precomputed else ExposuresPath.DIRECT_SCAN
            for is_precomputed in stored
            if is_precomputed is not None
        )

    def has_completed(self, calculation_config: MetricCalculationConfig, *, window: datetime) -> bool:
        """Whether a recalculation already stored a completed result for this calculation config at this window."""
        return ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            query_to=window,
            fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
            status=_COMPLETED,
        ).exists()

    def latest_daily_point(
        self, calculation_config: MetricCalculationConfig, *, since: datetime, until: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point of this calculation config with the latest query_to inside [since, until]."""
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            fingerprint=calculation_config.calculation_key(),
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

    def current_outcome(self, calculation_config: MetricCalculationConfig) -> ResultSummary | None:
        """The current result of the metric that `calculation_config` describes. `current_outcomes` defines the rule."""
        return self.current_outcomes({self.experiment_id: calculation_config}).get(self.experiment_id)

    def current_result(self, calculation_config: MetricCalculationConfig) -> MetricResultStats | None:
        """The statistics of the result that `current_outcome` picks, or None when it has none or doesn't parse."""
        response = self.current_response(calculation_config)
        return MetricResultStats.from_response(response) if response is not None else None

    def current_response(self, calculation_config: MetricCalculationConfig) -> ExperimentQueryResponse | None:
        """The baseline and variant results of the result that `current_outcome` picks, or None when it has none or
        doesn't parse."""
        stored = self._current_rows({self.experiment_id: calculation_config}).values_list("result", flat=True).first()
        return parse_stored_response(stored)

    def current_data_until(self, calculation_config: MetricCalculationConfig) -> datetime | None:
        """When the data of the result that `current_outcome` picks ends, as `current_outcomes` defines it, or None when
        it has none."""
        # F() selects the alias, which values_list can't select by name.
        rows = self._current_rows({self.experiment_id: calculation_config})
        return rows.values_list(F("data_until"), flat=True).first()

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

    def record_run_result(
        self,
        recalculation_id: str,
        calculation_config: MetricCalculationConfig,
        *,
        window: datetime,
        query_from: datetime,
        result: dict[str, Any],
        query_id: str | None,
    ) -> bool:
        """Store the completed result of one metric of a recalculation run, unless the run is terminal or missing.

        Returns whether the result was stored.
        """
        return self._record_for_run(
            recalculation_id,
            calculation_config,
            window=window,
            query_from=query_from,
            status=_COMPLETED,
            result=result,
            error_message=None,
            query_id=query_id,
        )

    def record_run_failure(
        self,
        recalculation_id: str,
        calculation_config: MetricCalculationConfig,
        *,
        window: datetime,
        query_from: datetime,
        error_message: str,
        query_id: str | None,
    ) -> None:
        """Store the failure of one metric of a recalculation run, unless the run is terminal or missing."""
        self._record_for_run(
            recalculation_id,
            calculation_config,
            window=window,
            query_from=query_from,
            status=_FAILED,
            result=None,
            error_message=error_message,
            query_id=query_id,
        )

    def record_daily_point(
        self, metric_uuid: str, calculation_key: str, *, window: datetime, query_from: datetime, result: dict[str, Any]
    ) -> None:
        """Store a completed daily point under the bare calculation key. The backfill stores its past days here too."""
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            query_from=query_from,
            status=_COMPLETED,
            result=result,
            error_message=None,
            query_id=None,
            completed_at=django_timezone.now(),
        )

    def record_daily_failure(
        self, metric_uuid: str, calculation_key: str, *, window: datetime, query_from: datetime, error_message: str
    ) -> None:
        """Store a failed daily point under the bare calculation key, unless a completed row under another
        fingerprint holds the window.

        That row is usually a recalculation of a stopped experiment, because a late daily run and the recalculation
        both use `end_date`. The run finds its row only by the salted key, and a failure has no result to put in its
        place, so the store keeps the row and drops the failure. A completed point under the same key gets the
        failure, so the timeseries shows the latest attempt at that window.
        """
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            query_from=query_from,
            status=_FAILED,
            result=None,
            error_message=error_message,
            query_id=None,
            completed_at=None,
            keep_completed_row_of_other_fingerprint=True,
        )

    def copy_into_sync_run(
        self,
        window: datetime,
        points: Iterable[tuple[MetricCalculationConfig, ExperimentMetricResult]],
        *,
        query_from: datetime,
        completed_at: datetime,
    ) -> None:
        """Copy daily points into a timeseries sync run at its window, under the salted keys a run read looks for."""
        for calculation_config, point in points:
            self._upsert(
                calculation_config.metric_id,
                window,
                fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
                query_from=query_from,
                status=_COMPLETED,
                result=point.result,
                error_message=None,
                query_id=None,
                completed_at=completed_at,
            )

    def delete_daily_points(self, metric_uuid: str, calculation_key: str) -> None:
        """Delete every row of a metric under the bare calculation key, which holds its daily and backfilled points."""
        ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id, metric_uuid=metric_uuid, fingerprint=calculation_key
        ).delete()

    def _record_for_run(
        self,
        recalculation_id: str,
        calculation_config: MetricCalculationConfig,
        *,
        window: datetime,
        query_from: datetime,
        status: str,
        result: dict[str, Any] | None,
        error_message: str | None,
        query_id: str | None,
    ) -> bool:
        team_id = calculation_config.settings.team_id
        with transaction.atomic():
            # Match request_recalculation's lock order; result inserts also take an experiment FK lock.
            Experiment.objects.select_for_update(no_key=True).filter(id=self.experiment_id, team_id=team_id).exists()
            current_status = (
                ExperimentMetricsRecalculation.objects.select_for_update()
                .filter(id=recalculation_id, experiment_id=self.experiment_id, team_id=team_id)
                .values_list("status", flat=True)
                .first()
            )
            if current_status is None or current_status in _TERMINAL_RECALC_STATUSES:
                logger.warning(
                    "Skipping experiment metric result write for a terminal or missing recalculation",
                    recalculation_id=recalculation_id,
                    metric_uuid=calculation_config.metric_id,
                    recalculation_status=current_status,
                )
                return False

            self._upsert(
                calculation_config.metric_id,
                window,
                fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
                query_from=query_from,
                status=status,
                result=result,
                error_message=error_message,
                query_id=query_id,
                completed_at=django_timezone.now() if status == _COMPLETED else None,
            )
            return True

    def _upsert(
        self,
        metric_uuid: str,
        window: datetime,
        *,
        fingerprint: str,
        query_from: datetime,
        status: str,
        result: dict[str, Any] | None,
        error_message: str | None,
        query_id: str | None,
        completed_at: datetime | None,
        keep_completed_row_of_other_fingerprint: bool = False,
    ) -> None:
        fields: dict[str, Any] = {
            "fingerprint": fingerprint,
            "query_from": query_from,
            "status": status,
            "result": result,
            "query_id": query_id,
            "completed_at": completed_at,
            "error_message": error_message,
        }
        with transaction.atomic():
            # Upsert on the true unique key (experiment, metric_uuid, query_to); fingerprint goes in the updated fields
            # so a row already occupying that key under a different fingerprint is updated in place, not inserted as a
            # colliding duplicate. When a concurrent write inserts the row first, get_or_create locks that row instead.
            row, created = ExperimentMetricResult.objects.select_for_update().get_or_create(
                experiment_id=self.experiment_id, metric_uuid=metric_uuid, query_to=window, defaults=fields
            )
            if created:
                return
            if keep_completed_row_of_other_fingerprint and row.status == _COMPLETED and row.fingerprint != fingerprint:
                logger.info(
                    "Keeping a completed experiment metric result that another fingerprint holds",
                    experiment_id=self.experiment_id,
                    metric_uuid=metric_uuid,
                    query_to=window,
                )
                return
            for name, value in fields.items():
                setattr(row, name, value)
            row.save(update_fields=[*fields, "updated_at"])

    @staticmethod
    def sync_copy_window(newest_point: datetime) -> datetime:
        """The query_to of a timeseries sync run and of the copies it holds, for daily points up to `newest_point`."""
        return newest_point + _SYNC_COPY_OFFSET

    @staticmethod
    def _current_rows(config_by_experiment: Mapping[int, MetricCalculationConfig]) -> QuerySet[ExperimentMetricResult]:
        """For each experiment, the row that `current_outcomes` describes."""
        filed_under_config = Q()
        for experiment_id, calculation_config in config_by_experiment.items():
            key = calculation_config.calculation_key()
            filed_under_config |= Q(
                experiment_id=experiment_id,
                metric_uuid=calculation_config.metric_id,
                fingerprint__in=[key, _recalc_fingerprint(key)],
            )
        return (
            ExperimentMetricResult.objects.filter(filed_under_config, status=_COMPLETED)
            # Postgres LEAST skips a NULL, so a row without completed_at ranks by its query_to.
            .alias(data_until=Least("query_to", "completed_at"))
            .order_by("experiment_id", F("data_until").desc(), F("completed_at").desc(nulls_last=True), "-id")
            .distinct("experiment_id")
        )

    @staticmethod
    def current_outcomes(config_by_experiment: Mapping[int, MetricCalculationConfig]) -> dict[int, ResultSummary]:
        """For each experiment, the current result of the metric that its calculation config describes, in one query.

        The current result is the completed row whose data ends last among the rows filed under the config's
        calculation key, by a recalculation run or by the daily workflows. A row's data ends at its query_to, or at
        its completed_at when that comes first. A backfill stamps the current day with the end of that day, but the
        row holds data only up to the moment the backfill ran, so a later run of the same day must win over it. A row
        under another key was computed from another configuration, for example from the start date before a
        relaunch, so it does not count. The end of the data counts, not the newest write, because a backfill writes
        past windows after the newer ones.
        """
        if not config_by_experiment:
            return {}
        rows = MetricResultStore._current_rows(config_by_experiment).values(
            "experiment_id",
            "metric_uuid",
            "completed_at",
            "query_to",
            baseline_samples=KT("result__baseline__number_of_samples"),
            baseline_sum=KT("result__baseline__sum"),
            variant_results=KeyTransform("variant_results", "result"),
        )
        summaries: dict[int, ResultSummary] = {}
        for row in rows:
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


def record_daily_metric_result(
    experiment_id: int,
    *,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    result: dict[str, Any],
) -> None:
    """Store a completed daily point, for the scheduled workflows outside the product."""
    MetricResultStore(experiment_id=experiment_id).record_daily_point(
        metric_uuid, calculation_key, window=window, query_from=query_from, result=result
    )


def record_daily_metric_failure(
    experiment_id: int,
    *,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    error_message: str,
) -> None:
    """Store a failed daily point, for the scheduled workflows outside the product."""
    MetricResultStore(experiment_id=experiment_id).record_daily_failure(
        metric_uuid, calculation_key, window=window, query_from=query_from, error_message=error_message
    )
