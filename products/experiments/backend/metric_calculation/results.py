"""Reads and writes of stored metric results.

`MetricResultStore` is the only module that reads or writes `ExperimentMetricResult`. Its named queries and writes
hide two storage conventions from the callers:

- A recalculation run files its rows under a salted calculation key (`_recalc_fingerprint`), and the daily
  timeseries workflows file theirs under the bare key. So the run reads, the reuse check and the chart never find
  the other family's rows. Only the current outcome reads both, because both hold results of the same calculation.
- The timeseries sync copies daily points into a run one second past the newest point (`sync_copy_window`).

The calculation key includes the start date, so no reader needs `query_from` to tell a relaunch apart.

Rows written before calculation key version 2 carry the legacy key (`MetricCalculationConfig.legacy_key`), which leaves out
several analytical inputs. No reuse check accepts them. The readers that show results (the run read, the cold-start
read, the chart and the current outcome) fall back to them only where no row under the current key covers the same
metric, window or day, and they mark such a result `legacy`. The run read does so only for a run that finished
before the first write under the current keys. The daily significance check never reads them.

Every write also stores the legacy key of its calculation config in `display_key`, salted like the fingerprint on a
run row. The legacy key hashes only inputs that the experiment owns. So after a team setting changes the current key, the chart
and the current outcome still find the rows written under the earlier key, and show them as `legacy` history. For
rows from before key version 2, the fingerprint itself is the legacy key, so one rule covers both. The run read and
the cold-start read do not use `display_key`: after such a change they must leave the metric uncovered, so that the
results page computes it under the new settings.

Several rows can share `(experiment, metric_uuid, query_to)` once the unique constraint on that key goes. Every
query that can meet such rows returns the one with the newest `completed_at`, then the highest id. It never looks a
row up with `.get()` on that key. While the constraint holds, no two rows tie, so this order changes no result.

Every write looks the row up on `(experiment, metric_uuid, query_to)` and stores the fingerprint as an updated
field. A row that holds the window under another fingerprint is therefore updated in place, and no write can
violate the unique constraint or create a second row for a window.

Every query filters on the experiment first, so the `(experiment, metric_uuid, query_to)` indexes serve it.
"""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.fields.json import KT, KeyTransform
from django.utils import timezone as django_timezone

import structlog

from posthog.dataclasses import frozen

from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_calculation_configs,
    find_calculation_config_by_key,
)
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


def _newest_write_first(
    rows: QuerySet[ExperimentMetricResult], *window_order: str | Case
) -> QuerySet[ExperimentMetricResult]:
    """Order `rows` by `window_order`, then put the newest write first among rows that tie on it."""
    return rows.order_by(*window_order, F("completed_at").desc(nulls_last=True), F("id").desc())


def _current_key_first(current_keys: Iterable[str]) -> Case:
    """An ordering that puts the rows under one of `current_keys` before the rows under any other key."""
    return Case(When(fingerprint__in=list(current_keys), then=Value(0)), default=Value(1), output_field=IntegerField())


@frozen
class StoredResult:
    """A stored result row and the key family a reader found it under."""

    row: ExperimentMetricResult
    # True when the row does not carry the current key of the calculation config. Its result may come from other
    # settings than the config's, so it is shown as history and never reused.
    legacy: bool


@frozen
class DailyTimeseries:
    """The stored results of one metric, one row per day."""

    by_day: dict[date, ExperimentMetricResult]
    # The days whose row does not carry the current key, because no row under the current key covers them.
    legacy_days: frozenset[date]
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
    # True when the result does not carry the current key, because no result under the current key exists.
    legacy: bool


@frozen
class MetricResultStore:
    """The stored metric results of one experiment."""

    experiment_id: int

    def for_run(self, run: ExperimentMetricsRecalculation) -> list[StoredResult]:
        """The rows of a recalculation run, one per metric uuid, ordered by metric uuid.

        A run has no link to its rows. The rows are found by the salted keys of the run's metrics under the
        current configuration of the experiment, at the run's query_to. A metric that no longer resolves on the
        experiment has no key, so its row is not found. A configuration change after the run changes the keys, so
        the run's rows are not found until the configuration changes back.

        A run from before key version 2 holds rows under the legacy keys. Such a row is returned as legacy when the
        metric has no row under its current key at the window, so that the results page shows the run complete
        instead of starting a new run to fill the gaps. Only a run that finished before the first write under its
        metrics' current keys gets legacy rows. A run in progress has not computed its metrics yet, so a legacy row
        would show an old result as a new one. A run that finished later recomputed every metric it reached, because
        no legacy row counts for reuse, so a metric it left without a row under the current key is one it did not
        compute.
        """
        if run.query_to is None:
            return []
        calculation_configs = {
            calculation_config.metric_id: calculation_config
            for calculation_config in build_calculation_configs(run.experiment)
        }
        run_configs = [
            calculation_configs[metric_uuid]
            for metric_uuid in dict.fromkeys(run.metric_uuids or [])
            if metric_uuid in calculation_configs
        ]
        if not run_configs:
            return []
        filed_under_run_keys = Q()
        for calculation_config in run_configs:
            filed_under_run_keys |= Q(
                metric_uuid=calculation_config.metric_id,
                fingerprint__in=[
                    _recalc_fingerprint(calculation_config.calculation_key()),
                    _recalc_fingerprint(calculation_config.legacy_key()),
                ],
            )
        current_keys = {_recalc_fingerprint(calculation_config.calculation_key()) for calculation_config in run_configs}
        # The recalc fingerprint is per config, not per run, so each window of a running experiment holds a row under
        # the same fingerprint. Without the query_to filter a later run would return every earlier window's row.
        rows = ExperimentMetricResult.objects.filter(
            filed_under_run_keys, experiment_id=self.experiment_id, query_to=run.query_to
        )
        stored = [
            StoredResult(row=row, legacy=row.fingerprint not in current_keys)
            for row in _newest_write_first(rows, "metric_uuid", _current_key_first(current_keys)).distinct(
                "metric_uuid"
            )
        ]
        if any(item.legacy for item in stored) and not self._finished_before_current_keys(run, run_configs):
            return [item for item in stored if not item.legacy]
        return stored

    def _finished_before_current_keys(
        self, run: ExperimentMetricsRecalculation, calculation_configs: list[MetricCalculationConfig]
    ) -> bool:
        """Whether the run finished before any row of its metrics was written under a current key, bare or salted."""
        if run.status not in _TERMINAL_RECALC_STATUSES or run.completed_at is None:
            return False
        current_keys = [
            key
            for calculation_config in calculation_configs
            for key in (calculation_config.calculation_key(), _recalc_fingerprint(calculation_config.calculation_key()))
        ]
        return not ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid__in=[calculation_config.metric_id for calculation_config in calculation_configs],
            fingerprint__in=current_keys,
            updated_at__lte=run.completed_at,
        ).exists()

    def has_completed(self, calculation_config: MetricCalculationConfig, *, window: datetime) -> bool:
        """Whether a recalculation already stored a completed result for this calculation config at this window. A
        result under the legacy key never counts."""
        return ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            query_to=window,
            fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
            status=_COMPLETED,
        ).exists()

    def latest_daily_point(
        self, calculation_config: MetricCalculationConfig, *, since: datetime, until: datetime, include_legacy: bool
    ) -> StoredResult | None:
        """The completed daily point of this calculation config with the latest query_to inside [since, until].

        With `include_legacy`, a point under the legacy key stands in when no point under the current key falls
        inside the range. A caller that copies the point into a run must leave it out, because a copy is filed
        under the current key and a later run would reuse it.
        """
        current_key = calculation_config.calculation_key()
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            fingerprint__in=[current_key, calculation_config.legacy_key()] if include_legacy else [current_key],
            status=_COMPLETED,
            query_to__gte=since,
            query_to__lte=until,
        )
        row = _newest_write_first(rows, _current_key_first([current_key]), "-query_to").first()
        return StoredResult(row=row, legacy=row.fingerprint != current_key) if row is not None else None

    def timeseries(self, calculation_config: MetricCalculationConfig, *, timezone: ZoneInfo) -> DailyTimeseries:
        """The daily rows of one metric, whatever their status, one per day of `timezone`.

        Only daily rows carry the bare key, because a recalculation salts it. The latest query_to inside a day
        stands for that day. A day without a row under the current key shows a row whose fingerprint or display key
        is the legacy key, if it has one. So the history from before key version 2, and the history from before a
        team setting changed, still render.
        """
        current_key = calculation_config.calculation_key()
        legacy_key = calculation_config.legacy_key()
        rows = list(
            _newest_write_first(
                ExperimentMetricResult.objects.filter(
                    Q(fingerprint__in=[current_key, legacy_key]) | Q(display_key=legacy_key),
                    experiment_id=self.experiment_id,
                    metric_uuid=calculation_config.metric_id,
                ),
                _current_key_first([current_key]),
                "-query_to",
            )
        )
        by_day: dict[date, ExperimentMetricResult] = {}
        legacy_days: set[date] = set()
        shown: list[ExperimentMetricResult] = []
        for row in rows:
            # A daily row's query_to is the exclusive end of its day, so the microsecond before it falls inside
            # the day the row covers.
            day = (row.query_to - timedelta(microseconds=1)).astimezone(timezone).date()
            legacy = row.fingerprint != current_key
            # Rows under the current key come first, so a legacy row only fills a day that none of them covers.
            if legacy and day in by_day and day not in legacy_days:
                continue
            by_day.setdefault(day, row)
            if legacy:
                legacy_days.add(day)
            shown.append(row)
        shown.sort(key=lambda row: row.query_to)
        return DailyTimeseries(
            by_day=by_day,
            legacy_days=frozenset(legacy_days),
            earliest=shown[0] if shown else None,
            latest=shown[-1] if shown else None,
        )

    def current_outcome(self, calculation_config: MetricCalculationConfig) -> ResultSummary | None:
        """The current result of the metric that `calculation_config` describes. `current_outcomes` defines the rule."""
        return self.current_outcomes({self.experiment_id: calculation_config}).get(self.experiment_id)

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
    ) -> None:
        """Store the completed result of one metric of a recalculation run, unless the run is terminal or missing."""
        self._record_for_run(
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
        self,
        metric_uuid: str,
        calculation_key: str,
        *,
        calculation_config: MetricCalculationConfig | None,
        window: datetime,
        query_from: datetime,
        result: dict[str, Any],
    ) -> None:
        """Store a completed daily point under the bare calculation key. The backfill stores its past days here too.

        `calculation_config` is the config that `calculation_key` was derived from, or None when the caller does not
        have it.
        """
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            display_key=calculation_config.legacy_key() if calculation_config is not None else None,
            query_from=query_from,
            status=_COMPLETED,
            result=result,
            error_message=None,
            query_id=None,
            completed_at=django_timezone.now(),
        )

    def record_daily_failure(
        self,
        metric_uuid: str,
        calculation_key: str,
        *,
        calculation_config: MetricCalculationConfig | None,
        window: datetime,
        query_from: datetime,
        error_message: str,
    ) -> None:
        """Store a failed daily point under the bare calculation key. `calculation_config` is as for
        `record_daily_point`."""
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            display_key=calculation_config.legacy_key() if calculation_config is not None else None,
            query_from=query_from,
            status=_FAILED,
            result=None,
            error_message=error_message,
            query_id=None,
            completed_at=None,
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
                display_key=_recalc_fingerprint(calculation_config.legacy_key()),
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
    ) -> None:
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
                return

            self._upsert(
                calculation_config.metric_id,
                window,
                fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
                display_key=_recalc_fingerprint(calculation_config.legacy_key()),
                query_from=query_from,
                status=status,
                result=result,
                error_message=error_message,
                query_id=query_id,
                completed_at=django_timezone.now() if status == _COMPLETED else None,
            )

    def _upsert(
        self,
        metric_uuid: str,
        window: datetime,
        *,
        fingerprint: str,
        display_key: str | None,
        query_from: datetime,
        status: str,
        result: dict[str, Any] | None,
        error_message: str | None,
        query_id: str | None,
        completed_at: datetime | None,
    ) -> None:
        # Upsert on the true unique key (experiment, metric_uuid, query_to); fingerprint goes in defaults so a row
        # already occupying that key under a different fingerprint is updated in place, not inserted as a colliding
        # duplicate.
        ExperimentMetricResult.objects.update_or_create(
            experiment_id=self.experiment_id,
            metric_uuid=metric_uuid,
            query_to=window,
            defaults={
                "fingerprint": fingerprint,
                "display_key": display_key,
                "query_from": query_from,
                "status": status,
                "result": result,
                "query_id": query_id,
                "completed_at": completed_at,
                "error_message": error_message,
            },
        )

    @staticmethod
    def sync_copy_window(newest_point: datetime) -> datetime:
        """The query_to of a timeseries sync run and of the copies it holds, for daily points up to `newest_point`."""
        return newest_point + _SYNC_COPY_OFFSET

    @staticmethod
    def current_outcomes(config_by_experiment: Mapping[int, MetricCalculationConfig]) -> dict[int, ResultSummary]:
        """For each experiment, the current result of the metric that its calculation config describes, in one query.

        The current result is the completed row with the newest query_to among the rows filed under the config's
        calculation key, by a recalculation run or by the daily workflows. A row under another key was computed from
        another configuration, for example from the start date before a relaunch, so it does not count. The newest
        window counts, not the newest write, because a backfill writes past windows after the newer ones.

        When no row carries the calculation key, the newest row whose fingerprint or display key is the legacy key stands
        in, marked legacy.
        """
        if not config_by_experiment:
            return {}
        filed_under_config = Q()
        current_keys: set[str] = set()
        for experiment_id, calculation_config in config_by_experiment.items():
            key, legacy_key = calculation_config.calculation_key(), calculation_config.legacy_key()
            legacy_keys = [legacy_key, _recalc_fingerprint(legacy_key)]
            current_keys |= {key, _recalc_fingerprint(key)}
            filed_under_config |= Q(experiment_id=experiment_id, metric_uuid=calculation_config.metric_id) & (
                Q(fingerprint__in=[key, _recalc_fingerprint(key), *legacy_keys]) | Q(display_key__in=legacy_keys)
            )
        rows = (
            ExperimentMetricResult.objects.filter(filed_under_config, status=_COMPLETED)
            .order_by(
                "experiment_id",
                _current_key_first(current_keys),
                "-query_to",
                F("completed_at").desc(nulls_last=True),
                "-id",
            )
            .distinct("experiment_id")
            .values(
                "experiment_id",
                "metric_uuid",
                "fingerprint",
                "completed_at",
                "query_to",
                baseline_samples=KT("result__baseline__number_of_samples"),
                baseline_sum=KT("result__baseline__sum"),
                variant_results=KeyTransform("variant_results", "result"),
            )
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
                legacy=row["fingerprint"] not in current_keys,
            )
        return summaries


def previous_completed_metric_result(
    experiment_id: int, *, team_id: int, metric_uuid: str, calculation_key: str, before: datetime
) -> dict[str, Any] | None:
    """The stored result of the completed daily point under this key with the latest query_to before `before`,
    for callers outside the product. None when there is no such point or the experiment is not in the team.

    A point under another key, the legacy key included, never stands in. It can come from other settings, so a
    comparison with it would not tell whether the current settings crossed a threshold.
    """
    if not Experiment.objects.filter(id=experiment_id, team_id=team_id).exists():
        return None
    row = MetricResultStore(experiment_id=experiment_id).previous_completed(metric_uuid, calculation_key, before=before)
    return row.result if row is not None else None


def _daily_calculation_config(
    experiment_id: int, *, team_id: int, metric_uuid: str, calculation_key: str
) -> MetricCalculationConfig | None:
    experiment = (
        Experiment.objects.select_related("team", "feature_flag").filter(id=experiment_id, team_id=team_id).first()
    )
    calculation_config = (
        find_calculation_config_by_key(experiment, metric_uuid, calculation_key) if experiment is not None else None
    )
    if calculation_config is None:
        logger.info(
            "Storing a daily metric result without a display key, because no metric of the experiment has its key",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
        )
    return calculation_config


def record_daily_metric_result(
    experiment_id: int,
    *,
    team_id: int,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    result: dict[str, Any],
) -> None:
    """Store a completed daily point, for the scheduled workflows outside the product.

    The row's display key is the legacy key of the metric's calculation config under the current configuration of
    the experiment, when that config gives `calculation_key`. The key comes from the daily discovery, so a
    configuration change since then leaves the row without a display key. So does an `experiment_id` that is not in
    the team.
    """
    calculation_config = _daily_calculation_config(
        experiment_id, team_id=team_id, metric_uuid=metric_uuid, calculation_key=calculation_key
    )
    MetricResultStore(experiment_id=experiment_id).record_daily_point(
        metric_uuid,
        calculation_key,
        calculation_config=calculation_config,
        window=window,
        query_from=query_from,
        result=result,
    )


def record_daily_metric_failure(
    experiment_id: int,
    *,
    team_id: int,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    error_message: str,
) -> None:
    """Store a failed daily point, for the scheduled workflows outside the product. The row gets its display key
    as `record_daily_metric_result` describes."""
    calculation_config = _daily_calculation_config(
        experiment_id, team_id=team_id, metric_uuid=metric_uuid, calculation_key=calculation_key
    )
    MetricResultStore(experiment_id=experiment_id).record_daily_failure(
        metric_uuid,
        calculation_key,
        calculation_config=calculation_config,
        window=window,
        query_from=query_from,
        error_message=error_message,
    )
