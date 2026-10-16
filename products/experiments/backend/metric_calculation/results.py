"""Reads and writes of stored metric results.

`MetricResultStore` is the only module that reads or writes `ExperimentMetricResult`. Its named queries and writes
hide two storage conventions from the callers:

- A recalculation run files its rows under a salted calculation key (`_recalc_fingerprint`), and the daily
  timeseries workflows file theirs under the bare key. So the run reads, the reuse check and the chart never find
  the other family's rows. Only the current outcome reads both, because both hold results of the same calculation.
- The timeseries sync copies daily points into a run one second past the newest point (`sync_copy_window`).

The calculation key includes the start date, so no reader needs `query_from` to tell a relaunch apart.

Rows written before calculation key version 2 carry the version 1 key (`MetricCalculationConfig.legacy_key`), which
leaves out several analytical inputs. A one-time conversion after the deploy gives each such row the version 2 key of
the experiment's current configuration. Until then, every reader falls back to the version 1 key of the current
config where no row under the version 2 key covers the same metric, window or day. This includes the reuse check, so
before the conversion a reuse behaves as it did under version 1. After the conversion no row carries the current
version 1 key as its fingerprint, and the fallback finds nothing.

Every write also stores the version 1 key of its calculation config in `display_key`, salted like the fingerprint on
a run row. The version 1 key hashes only inputs that the experiment owns. So after a team setting changes the
current key, the chart, the current outcome and the significance baseline still find the rows written under the
earlier key. The run read, the reuse check and the cold-start read do not use `display_key`: after such a change
they must leave the metric uncovered, so that the results page computes it under the new settings.

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
from django.db.models import BooleanField, Case, F, Q, QuerySet, Value, When
from django.db.models.fields.json import KT, KeyTransform
from django.db.models.functions import Least
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


def _current_key_first(under_current_key: Q) -> Case:
    """An ascending order on this puts the rows that `under_current_key` matches first."""
    return Case(When(under_current_key, then=Value(False)), default=Value(True), output_field=BooleanField())


@frozen
class DailyTimeseries:
    """The stored results of one metric, one row per day."""

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

        A row under the salted version 1 key stands in for a metric that has no row under its version 2 key at the
        window. So a run from before key version 2, or a reuse of such a row, still reads complete.
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
        current_keys: set[str] = set()
        for calculation_config in run_configs:
            current_key = _recalc_fingerprint(calculation_config.calculation_key())
            current_keys.add(current_key)
            filed_under_run_keys |= Q(
                metric_uuid=calculation_config.metric_id,
                fingerprint__in=[current_key, _recalc_fingerprint(calculation_config.legacy_key())],
            )
        # The recalc fingerprint is per config, not per run, so each window of a running experiment holds a row under
        # the same fingerprint. Without the query_to filter a later run would return every earlier window's row.
        rows = ExperimentMetricResult.objects.filter(
            filed_under_run_keys, experiment_id=self.experiment_id, query_to=run.query_to
        )
        return list(
            _newest_write_first(rows, "metric_uuid", _current_key_first(Q(fingerprint__in=current_keys))).distinct(
                "metric_uuid"
            )
        )

    def has_completed(self, calculation_config: MetricCalculationConfig, *, window: datetime) -> bool:
        """Whether a recalculation already stored a completed result for this calculation config at this window, under
        the version 2 key or, for a row that the conversion has not reached, the version 1 key."""
        return ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            query_to=window,
            fingerprint__in=[
                _recalc_fingerprint(calculation_config.calculation_key()),
                _recalc_fingerprint(calculation_config.legacy_key()),
            ],
            status=_COMPLETED,
        ).exists()

    def latest_daily_point(
        self, calculation_config: MetricCalculationConfig, *, since: datetime, until: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point of this calculation config with the latest query_to inside [since, until]. A
        point under the version 1 key stands in when no point under the version 2 key falls inside the range."""
        current_key = calculation_config.calculation_key()
        rows = ExperimentMetricResult.objects.filter(
            experiment_id=self.experiment_id,
            metric_uuid=calculation_config.metric_id,
            fingerprint__in=[current_key, calculation_config.legacy_key()],
            status=_COMPLETED,
            query_to__gte=since,
            query_to__lte=until,
        )
        return _newest_write_first(rows, _current_key_first(Q(fingerprint=current_key)), "-query_to").first()

    def timeseries(self, calculation_config: MetricCalculationConfig, *, timezone: ZoneInfo) -> DailyTimeseries:
        """The daily rows of one metric, whatever their status, one per day of `timezone`.

        Only daily rows carry the bare key, because a recalculation salts it. The latest query_to inside a day
        stands for that day. A day without a row under the version 2 key shows a row whose fingerprint or display
        key is the version 1 key, if it has one. So the history from before key version 2, and the history from
        before a team setting changed, still render.
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
                _current_key_first(Q(fingerprint=current_key)),
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
            under_earlier_key = row.fingerprint != current_key
            # Rows under the current key come first, so a row under an earlier key only fills a day that none of
            # them covers.
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
        )

    def current_outcome(self, calculation_config: MetricCalculationConfig) -> ResultSummary | None:
        """The current result of the metric that `calculation_config` describes. `current_outcomes` defines the rule."""
        return self.current_outcomes({self.experiment_id: calculation_config}).get(self.experiment_id)

    def previous_completed(
        self, metric_uuid: str, calculation_key: str, *, legacy_key: str | None, before: datetime
    ) -> ExperimentMetricResult | None:
        """The completed daily point under this key with the latest query_to before `before`.

        Without such a point, the latest earlier point whose fingerprint or display key is `legacy_key` stands in.
        That is the point that the comparison used under key version 1, so a settings change that version 1 does
        not cover does not make the next point look like a new transition.
        """
        under_key = Q(fingerprint=calculation_key)
        if legacy_key is not None:
            under_key |= Q(fingerprint=legacy_key) | Q(display_key=legacy_key)
        rows = ExperimentMetricResult.objects.filter(
            under_key,
            experiment_id=self.experiment_id,
            metric_uuid=metric_uuid,
            status=_COMPLETED,
            query_to__lt=before,
        )
        return _newest_write_first(rows, _current_key_first(Q(fingerprint=calculation_key)), "-query_to").first()

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
        """Store a failed daily point under the bare calculation key, unless a completed row under another
        fingerprint holds the window. `calculation_config` is as for `record_daily_point`.

        That row is usually a recalculation of a stopped experiment, because a late daily run and the recalculation
        both use `end_date`. The run finds its row only by the salted key, and a failure has no result to put in its
        place, so the store keeps the row and drops the failure. A completed point under the same key gets the
        failure, so the timeseries shows the latest attempt at that window.
        """
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
        """Copy daily points into a timeseries sync run at its window, under the salted keys a run read looks for.

        Each copy carries the salted form of its point's own key, which is the version 2 or the version 1 key of the
        config. So a point that the conversion has not reached yet gets a copy that the conversion also reaches.
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
        keep_completed_row_of_other_fingerprint: bool = False,
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
    def current_outcomes(config_by_experiment: Mapping[int, MetricCalculationConfig]) -> dict[int, ResultSummary]:
        """For each experiment, the current result of the metric that its calculation config describes, in one query.

        The current result is the completed row whose data ends last among the rows filed under the config's
        calculation key, by a recalculation run or by the daily workflows. A row's data ends at its query_to, or at
        its completed_at when that comes first. A backfill stamps the current day with the end of that day, but the
        row holds data only up to the moment the backfill ran, so a later run of the same day must win over it. A row
        under another key was computed from another configuration, for example from the start date before a
        relaunch, so it does not count. The end of the data counts, not the newest write, because a backfill writes
        past windows after the newer ones.

        When no row carries the calculation key, the row whose fingerprint or display key is the version 1 key and
        whose data ends last stands in. Each experiment's rows rank by that experiment's own keys. A calculation key
        hashes no experiment id, so the earlier key of one experiment can be the current key of another.
        """
        if not config_by_experiment:
            return {}
        filed_under_config = Q()
        under_current_key = Q()
        for experiment_id, calculation_config in config_by_experiment.items():
            key, legacy_key = calculation_config.calculation_key(), calculation_config.legacy_key()
            current_keys = [key, _recalc_fingerprint(key)]
            legacy_keys = [legacy_key, _recalc_fingerprint(legacy_key)]
            under_current_key |= Q(experiment_id=experiment_id, fingerprint__in=current_keys)
            filed_under_config |= Q(experiment_id=experiment_id, metric_uuid=calculation_config.metric_id) & (
                Q(fingerprint__in=[*current_keys, *legacy_keys]) | Q(display_key__in=legacy_keys)
            )
        rows = (
            ExperimentMetricResult.objects.filter(filed_under_config, status=_COMPLETED)
            # Postgres LEAST skips a NULL, so a row without completed_at ranks by its query_to.
            .alias(
                data_until=Least("query_to", "completed_at"), under_earlier_key=_current_key_first(under_current_key)
            )
            .order_by(
                "experiment_id",
                "under_earlier_key",
                F("data_until").desc(),
                F("completed_at").desc(nulls_last=True),
                "-id",
            )
            .distinct("experiment_id")
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
            variant_results = row["variant_results"] if isinstance(row["variant_results"], list) else []
            summaries[row["experiment_id"]] = ResultSummary(
                completed_at=row["completed_at"],
                query_to=row["query_to"],
                baseline_samples=row["baseline_samples"],
                baseline_sum=row["baseline_sum"],
                variant_results=tuple(variant for variant in variant_results if isinstance(variant, dict)),
            )
        return summaries


def _experiment_in_team(experiment_id: int, team_id: int) -> Experiment | None:
    return Experiment.objects.select_related("team", "feature_flag").filter(id=experiment_id, team_id=team_id).first()


def previous_completed_metric_result(
    experiment_id: int, *, team_id: int, metric_uuid: str, calculation_key: str, before: datetime
) -> dict[str, Any] | None:
    """The stored result of the completed daily point under this key with the latest query_to before `before`,
    for callers outside the product. None when there is no such point or the experiment is not in the team.

    Without a point under this key, the point that key version 1 compared with stands in, as
    `MetricResultStore.previous_completed` describes. The version 1 key comes from the metric's calculation config
    under the current configuration of the experiment, when that config gives `calculation_key`.
    """
    experiment = _experiment_in_team(experiment_id, team_id)
    if experiment is None:
        return None
    calculation_config = find_calculation_config_by_key(experiment, metric_uuid, calculation_key)
    row = MetricResultStore(experiment_id=experiment_id).previous_completed(
        metric_uuid,
        calculation_key,
        legacy_key=calculation_config.legacy_key() if calculation_config is not None else None,
        before=before,
    )
    return row.result if row is not None else None


def _daily_calculation_config(
    experiment_id: int, *, team_id: int, metric_uuid: str, calculation_key: str
) -> MetricCalculationConfig | None:
    experiment = _experiment_in_team(experiment_id, team_id)
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
