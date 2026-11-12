"""Reads and writes of stored metric results.

`MetricResultStore` is the only module that reads or writes `ExperimentMetricResult`. Its named queries and writes
hide two storage conventions from the callers:

- A recalculation run files its rows under a salted calculation key (`_recalc_fingerprint`), and the daily
  timeseries workflows file theirs under the bare key. So the run reads, the reuse check and the chart never find
  the other family's rows. Only the current outcome reads both, because both hold results of the same calculation.
- The timeseries sync copies daily points into a run one second past the newest point (`sync_copy_window`).

The calculation key includes the start date, so no reader needs `query_from` to tell a relaunch apart.

A row carries the key of one key version (`MetricCalculationConfig.key_for_version`). Readers find the rows of the
current config under every key version, so rows that another key version wrote stay visible. The newest compatible
row wins, and rows under the current settings win only a tie. Calculation reuse requires the active key. Rows are never relabeled with
current settings: a version 1 key omits analytical inputs, so the settings of such a row are unknown.

A write can also store its config's version 1 key in `display_key`, salted like the fingerprint on a run row.
The chart, current outcome and significance baseline use it to preserve history across project setting changes.
Ended experiments also use it for run reads and cold-start display, so opening the page does not overwrite the
result after a project setting changes. Running experiments leave such run results uncovered and recompute.
Display readers know whether each result used current, previous, or unknown settings; display compatibility
never makes a result reusable for calculation.

Several rows can share `(experiment, metric_uuid, query_to)` once the unique constraint on that key goes. Every
query that can meet such rows returns the one with the newest `completed_at`, then the highest id. It never looks a
row up with `.get()` on that key. While the constraint holds, no two rows tie, so this order changes no result.

Every write looks the row up on `(experiment, metric_uuid, query_to)` and stores the fingerprint as an updated
field. A row that holds the window under another fingerprint is therefore updated in place, and no write can
violate the unique constraint or create a second row for a window. A failure is the exception: it leaves a
completed row under another fingerprint in place, because it has no result to replace that row with. A recalculation
failure also leaves a completed row under its own key in place, and the run keeps the failure in its `metric_errors`.

Every query filters on the experiment first, so the `(experiment, metric_uuid, query_to)` indexes serve it.
"""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import BooleanField, Case, F, Q, QuerySet, Value, When
from django.db.models.fields.json import KT, KeyTransform
from django.db.models.functions import Least
from django.utils import timezone as django_timezone

import structlog

from posthog.schema import ExperimentQueryResponse

from posthog.dataclasses import frozen

from products.experiments.backend.facade.enums import ExperimentResultConfigurationStatus, ExposuresPath
from products.experiments.backend.logic.result_stats import MetricResultStats, parse_stored_response
from products.experiments.backend.metric_calculation.config import (
    CALCULATION_KEY_VERSION,
    KEY_VERSIONS,
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


def _current_key_first(under_current_key: Q) -> Case:
    """An ascending order on this puts the rows that `under_current_key` matches first."""
    return Case(When(under_current_key, then=Value(False)), default=Value(True), output_field=BooleanField())


def _keys_of(config: MetricCalculationConfig, *, salted: bool = False) -> list[str]:
    """The keys of `config` in every key version, the active key first."""
    versions = [config.settings.key_version, *(v for v in KEY_VERSIONS if v != config.settings.key_version)]
    keys = [config.key_for_version(version) for version in versions]
    return [_recalc_fingerprint(key) for key in keys] if salted else keys


def _current_settings_keys(config: MetricCalculationConfig) -> list[str]:
    """The keys, bare and salted, of the rows that used the current settings of `config`. A version 2 key hashes every
    setting. A version 1 key omits settings, so its rows count only while version 1 is active."""
    versions = {CALCULATION_KEY_VERSION, config.settings.key_version}
    keys = [config.key_for_version(version) for version in versions]
    return [*keys, *(_recalc_fingerprint(key) for key in keys)]


def _under_current_settings(config: MetricCalculationConfig) -> Q:
    """The rows of `config` that used its current settings. The readers of the newest result order by the window
    first and by this only to break a tie, so the newest compatible row wins. So after the active key version
    changes, neither a newer row under the other version nor a newer row under earlier settings hides behind an older
    row under current settings."""
    return Q(fingerprint__in=_current_settings_keys(config))


def result_configuration_status(fingerprint: str | None, config: MetricCalculationConfig) -> str:
    """The provenance of a row of `config` that a reader found, relative to the active key version.

    A row that only its display key matched comes from other settings: writers store the display key with the
    version 2 key, because under version 1 the display key equals the fingerprint.
    """
    if fingerprint in _current_settings_keys(config):
        return ExperimentResultConfigurationStatus.CURRENT
    if fingerprint in _keys_of(config) + _keys_of(config, salted=True):
        return ExperimentResultConfigurationStatus.UNKNOWN
    return ExperimentResultConfigurationStatus.PREVIOUS


@frozen
class DailyTimeseries:
    """The stored results of one metric, one row per day."""

    by_day: dict[date, ExperimentMetricResult]
    earliest: ExperimentMetricResult | None
    latest: ExperimentMetricResult | None
    configuration_by_day: dict[date, str] = field(default_factory=dict)


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
    configuration_status: str = ExperimentResultConfigurationStatus.UNKNOWN


@frozen
class MetricResultStore:
    """The stored metric results of one experiment."""

    experiment_id: int

    def for_run(
        self,
        run: ExperimentMetricsRecalculation,
        *,
        configs: list[MetricCalculationConfig] | None = None,
        with_result: bool = True,
    ) -> list[ExperimentMetricResult]:
        """The rows of a recalculation run, one per metric uuid, ordered by metric uuid. With `with_result=False` the
        rows don't load `result`, which for a funnel holds the sessions of each step, and reading it queries again.

        A run has no link to its rows. The rows are found by the salted keys of the run's metrics under the
        current configuration of the experiment, at the run's query_to. A metric that no longer resolves on the
        experiment has no key, so its row is not found. Ended experiments also retain completed rows with a
        compatible display key; running experiments expose a gap after the calculation key changes.

        A row under the salted key of another key version stands in for a metric that has no row under its active key
        at the window. So a run that another key version wrote still reads complete.
        """
        if run.query_to is None:
            return []
        calculation_configs = {
            calculation_config.metric_id: calculation_config
            for calculation_config in (configs if configs is not None else build_calculation_configs(run.experiment))
        }
        run_configs = [
            calculation_configs[metric_uuid]
            for metric_uuid in dict.fromkeys(run.metric_uuids or [])
            if metric_uuid in calculation_configs
        ]
        if not run_configs:
            return []
        filed_under_run_keys = Q()
        under_current_settings = Q()
        for calculation_config in run_configs:
            run_keys = _keys_of(calculation_config, salted=True)
            filed_under_run_keys |= Q(metric_uuid=calculation_config.metric_id, fingerprint__in=run_keys)
            under_current_settings |= Q(metric_uuid=calculation_config.metric_id) & _under_current_settings(
                calculation_config
            )
            if run.experiment.is_stopped:
                filed_under_run_keys |= Q(
                    metric_uuid=calculation_config.metric_id,
                    display_key=_recalc_fingerprint(calculation_config.legacy_key()),
                    status=_COMPLETED,
                )
        # The recalc fingerprint is per config, not per run, so each window of a running experiment holds a row under
        # the same fingerprint. Without the query_to filter a later run would return every earlier window's row.
        rows = ExperimentMetricResult.objects.filter(
            filed_under_run_keys, experiment_id=self.experiment_id, query_to=run.query_to
        )
        if not with_result:
            rows = rows.defer("result")
        return list(
            _newest_write_first(rows, "metric_uuid", _current_key_first(under_current_settings)).distinct("metric_uuid")
        )

    def with_zero_baseline(self, rows: Iterable[ExperimentMetricResult]) -> list[ExperimentMetricResult]:
        """Those of these rows whose baseline reads zero on the metric or on its denominator, with `result`, in the order
        of `rows`. The database applies the filter, so the rows with a value don't load `result`."""
        by_pk = {row.pk: row for row in rows}
        loaded = ExperimentMetricResult.objects.filter(
            Q(result__baseline__sum=0) | Q(result__baseline__denominator_sum=0),
            experiment_id=self.experiment_id,
            pk__in=by_pk,
        ).in_bulk()
        return [loaded[pk] for pk in by_pk if pk in loaded]

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
        """Whether this exact calculation config already completed at this window."""
        return ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            query_to=window,
            fingerprint=_recalc_fingerprint(calculation_config.calculation_key()),
            status=_COMPLETED,
        ).exists()

    def latest_daily_point(
        self,
        calculation_config: MetricCalculationConfig,
        *,
        since: datetime,
        until: datetime,
        preserve_history: bool = False,
    ) -> ExperimentMetricResult | None:
        """The completed daily point of this calculation config with the latest query_to inside [since, until], under
        either key version. A point under current settings wins a tie on query_to."""
        keys = Q(fingerprint__in=_keys_of(calculation_config))
        if preserve_history:
            keys |= Q(display_key=calculation_config.legacy_key())
        rows = ExperimentMetricResult.objects.filter(
            keys,
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            status=_COMPLETED,
            query_to__gte=since,
            query_to__lte=until,
        )
        return _newest_write_first(
            rows, "-query_to", _current_key_first(_under_current_settings(calculation_config))
        ).first()

    def timeseries(self, calculation_config: MetricCalculationConfig, *, timezone: ZoneInfo) -> DailyTimeseries:
        """The daily rows of one metric, whatever their status, one per day of `timezone`.

        Only daily rows carry the bare key, because a recalculation salts it. The latest query_to inside a day
        stands for that day. A day without a row under the active key shows a row under another key version of the
        config, or whose display key is the version 1 key, if it has one. So the history that another key version
        wrote, and the history from before a team setting changed, still render.
        """
        current_keys = _current_settings_keys(calculation_config)
        rows = list(
            _newest_write_first(
                ExperimentMetricResult.objects.filter(
                    Q(fingerprint__in=_keys_of(calculation_config)) | Q(display_key=calculation_config.legacy_key()),
                    experiment_id=self.experiment_id,
                    metric_uuid=calculation_config.metric_id,
                ),
                _current_key_first(_under_current_settings(calculation_config)),
                "-query_to",
            )
        )
        by_day: dict[date, ExperimentMetricResult] = {}
        filled_by_earlier_key: set[date] = set()
        shown: list[ExperimentMetricResult] = []
        for row in rows:
            # A daily row's query_to is the exclusive end of its day, so the microsecond before it falls inside
            # the day the row covers.
            day = (row.query_to - timedelta(microseconds=1)).astimezone(timezone).date()
            under_earlier_key = row.fingerprint not in current_keys
            # Rows under current settings come first, so another row only fills a day that none of them covers.
            if under_earlier_key and day in by_day and day not in filled_by_earlier_key:
                continue
            by_day.setdefault(day, row)
            if under_earlier_key:
                filled_by_earlier_key.add(day)
            shown.append(row)
        return DailyTimeseries(
            by_day=by_day,
            earliest=min(shown, key=lambda row: row.query_to, default=None),
            latest=max(shown, key=lambda row: row.query_to, default=None),
            configuration_by_day={
                day: result_configuration_status(row.fingerprint, calculation_config) for day, row in by_day.items()
            },
        )

    def current_outcome(self, calculation_config: MetricCalculationConfig) -> ResultSummary | None:
        """The current result of the metric that `calculation_config` describes. `current_outcomes` defines the rule."""
        return self.current_outcomes({self.experiment_id: calculation_config}).get(self.experiment_id)

    def current_result(self, calculation_config: MetricCalculationConfig) -> MetricResultStats | None:
        """The statistics of the result that `current_outcome` picks, or None when it has none or doesn't parse."""
        response = self.current_response(calculation_config)
        if response is None:
            return None
        is_quantile = calculation_config.definition.get("metric_type") == "quantile"
        return MetricResultStats.from_response(response, is_quantile=is_quantile)

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
        self, metric_uuid: str, fingerprints: Iterable[str], *, display_key: str | None, before: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point with the latest query_to before `before` among the points under `fingerprints`
        or whose display key is `display_key`.

        The newest compatible point wins whatever its key. So neither a change of the key version nor a settings change
        that the display key does not cover makes the next point look like a new transition, and after settings
        change and change back, the point under the other settings is the baseline, not an older one.
        """
        under_key = Q(fingerprint__in=list(fingerprints))
        if display_key is not None:
            under_key |= Q(display_key=display_key)
        rows = ExperimentMetricResult.objects.filter(
            under_key,
            experiment_id=self.experiment_id,
            metric_uuid=metric_uuid,
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
        """Store the failure of one metric of a recalculation run, unless the run is terminal or missing, or a completed
        row holds the window. The caller records the failure in the run's `metric_errors` too, so the run reports it
        even when the completed row stays."""
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
        display_key: str | None = None,
        window: datetime,
        query_from: datetime,
        result: dict[str, Any],
    ) -> None:
        """Store a completed daily point under the bare calculation key. The backfill stores its past days here too.
        `display_key` is the version 1 key of the config that `calculation_key` belongs to. Without it the row has no
        display key, which only a reader under another key version or other settings misses."""
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            display_key=display_key,
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
        display_key: str | None = None,
        window: datetime,
        query_from: datetime,
        error_message: str,
    ) -> None:
        """Store a failed daily point under the bare calculation key, unless a completed row under another
        fingerprint holds the window. `display_key` is as for `record_daily_point`.

        That row is usually a recalculation of a stopped experiment, because a late daily run and the recalculation
        both use `end_date`. The run finds its row only by the salted key, and a failure has no result to put in its
        place, so the store keeps the row and drops the failure. A completed point under the same key gets the
        failure, so the timeseries shows the latest attempt at that window.
        """
        self._upsert(
            metric_uuid,
            window,
            fingerprint=calculation_key,
            display_key=display_key,
            query_from=query_from,
            status=_FAILED,
            result=None,
            error_message=error_message,
            query_id=None,
            completed_at=None,
            replaces_completed_row_of_same_fingerprint=True,
        )

    def copy_into_sync_run(
        self,
        window: datetime,
        points: Iterable[tuple[MetricCalculationConfig, ExperimentMetricResult]],
        *,
        query_from: datetime,
        completed_at: datetime,
    ) -> None:
        """Copy daily points into a timeseries sync run at its window, under the salted keys a run read looks for.

        Each copy retains its point's own key and provenance, including unknown settings on version 1 points.
        """
        for calculation_config, point in points:
            assert point.fingerprint is not None
            self._upsert(
                calculation_config.metric_id,
                window,
                fingerprint=_recalc_fingerprint(point.fingerprint),
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
                display_key=_recalc_fingerprint(calculation_config.legacy_key()),
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
        display_key: str | None,
        query_from: datetime,
        status: str,
        result: dict[str, Any] | None,
        error_message: str | None,
        query_id: str | None,
        completed_at: datetime | None,
        replaces_completed_row_of_same_fingerprint: bool = False,
    ) -> None:
        fields: dict[str, Any] = {
            "fingerprint": fingerprint,
            "display_key": display_key,
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
            replaces_completed_row = replaces_completed_row_of_same_fingerprint and row.fingerprint == fingerprint
            if status == _FAILED and row.status == _COMPLETED and not replaces_completed_row:
                logger.info(
                    "Keeping a completed experiment metric result instead of a failure",
                    experiment_id=self.experiment_id,
                    metric_uuid=metric_uuid,
                    query_to=window,
                    kept_fingerprint=row.fingerprint,
                    failed_fingerprint=fingerprint,
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
        under_current_settings = Q()
        for experiment_id, calculation_config in config_by_experiment.items():
            legacy_key = calculation_config.legacy_key()
            display_keys = [legacy_key, _recalc_fingerprint(legacy_key)]
            under_current_settings |= Q(experiment_id=experiment_id) & _under_current_settings(calculation_config)
            filed_under_config |= Q(experiment_id=experiment_id, metric_uuid=calculation_config.metric_id) & (
                Q(fingerprint__in=[*_keys_of(calculation_config), *_keys_of(calculation_config, salted=True)])
                | Q(display_key__in=display_keys)
            )
        return (
            ExperimentMetricResult.objects.filter(filed_under_config, status=_COMPLETED)
            # Postgres LEAST skips a NULL, so a row without completed_at ranks by its query_to.
            .alias(
                data_until=Least("query_to", "completed_at"),
                under_other_settings=_current_key_first(under_current_settings),
            )
            .order_by(
                "experiment_id",
                F("data_until").desc(),
                "under_other_settings",
                F("completed_at").desc(nulls_last=True),
                "-id",
            )
            .distinct("experiment_id")
        )

    @staticmethod
    def current_outcomes(config_by_experiment: Mapping[int, MetricCalculationConfig]) -> dict[int, ResultSummary]:
        """For each experiment, the current result of the metric that its calculation config describes, in one query.

        The current result is the completed row whose data ends last among the rows filed under the config's
        calculation key, by a recalculation run or by the daily workflows. A row's data ends at its query_to, or at
        its completed_at when that comes first. A backfill stamps the current day with the end of that day, but the
        row holds data only up to the moment the backfill ran, so a later run of the same day must win over it. A row
        whose key and display key both belong to another configuration, for example to the start date before a
        relaunch, does not count. The end of the data counts, not the newest write, because a backfill writes
        past windows after the newer ones.

        Rows under the other key version, and rows whose display key is the version 1 key, count too. The row whose
        data ends last wins, and a row under current settings wins a tie. Each experiment's rows rank by that
        experiment's own keys. A calculation key
        hashes no experiment id, so the earlier key of one experiment can be the current key of another.
        """
        if not config_by_experiment:
            return {}
        rows = MetricResultStore._current_rows(config_by_experiment).values(
            "experiment_id",
            "metric_uuid",
            "completed_at",
            "query_to",
            "fingerprint",
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
                configuration_status=result_configuration_status(
                    row["fingerprint"], config_by_experiment[row["experiment_id"]]
                ),
                baseline_samples=row["baseline_samples"],
                baseline_sum=row["baseline_sum"],
                variant_results=tuple(variant for variant in variant_results if isinstance(variant, dict)),
            )
        return summaries


def previous_completed_metric_result(
    experiment_id: int,
    *,
    team_id: int,
    metric_uuid: str,
    calculation_key: str,
    before: datetime,
    display_key: str | None = None,
) -> dict[str, Any] | None:
    """The stored result of the completed daily point that a new point under this key compares with, for callers
    outside the product. None when there is no such point or the experiment is not in the team.

    `MetricResultStore.previous_completed` picks the point among the points under this key, under the version 1 key
    `display_key`, or whose display key it is. Without `display_key`, the keys come from the metric's calculation config
    under the current configuration of the experiment when that config gives `calculation_key` in some key version.
    """
    experiment = (
        Experiment.objects.select_related("team", "feature_flag").filter(id=experiment_id, team_id=team_id).first()
    )
    if experiment is None:
        return None
    fingerprints = {calculation_key}
    if display_key is None:
        calculation_config = find_calculation_config_by_key(experiment, metric_uuid, calculation_key)
        if calculation_config is not None:
            fingerprints.update(_keys_of(calculation_config))
            display_key = calculation_config.legacy_key()
    else:
        fingerprints.add(display_key)
    row = MetricResultStore(experiment_id=experiment_id).previous_completed(
        metric_uuid, fingerprints, display_key=display_key, before=before
    )
    return row.result if row is not None else None


def record_daily_metric_result(
    experiment_id: int,
    *,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    result: dict[str, Any],
    display_key: str | None = None,
) -> None:
    """Store a completed daily point, for the scheduled workflows outside the product."""
    MetricResultStore(experiment_id=experiment_id).record_daily_point(
        metric_uuid, calculation_key, display_key=display_key, window=window, query_from=query_from, result=result
    )


def record_daily_metric_failure(
    experiment_id: int,
    *,
    metric_uuid: str,
    calculation_key: str,
    window: datetime,
    query_from: datetime,
    error_message: str,
    display_key: str | None = None,
) -> None:
    """Store a failed daily point, for the scheduled workflows outside the product."""
    MetricResultStore(experiment_id=experiment_id).record_daily_failure(
        metric_uuid,
        calculation_key,
        display_key=display_key,
        window=window,
        query_from=query_from,
        error_message=error_message,
    )
