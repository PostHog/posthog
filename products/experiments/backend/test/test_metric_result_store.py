from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from django.db import connection

from parameterized import parameterized

from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    get_metric_calculation_config,
)
from products.experiments.backend.metric_calculation.results import (
    MetricResultStore,
    compute_recalc_fingerprint,
    previous_completed_metric_result,
)
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_START = datetime(2026, 1, 1, tzinfo=UTC)
# Midnight, so a daily row with this query_to covers 9 January.
_WINDOW = datetime(2026, 1, 10, tzinfo=UTC)
_WINDOW_DAY = date(2026, 1, 9)


def test_recalc_fingerprint_is_deterministic_for_a_given_config():
    # The recalc fingerprint must NOT depend on the recalculation run: a stopped experiment re-recalculated
    # pins the same query_to, so a run-dependent fingerprint produced a new value each run and collided on the
    # (experiment, metric_uuid, query_to) unique constraint. Same config in, same fingerprint out, every run.
    config_fp = "a" * 64
    assert compute_recalc_fingerprint(config_fp) == compute_recalc_fingerprint(config_fp)


def test_recalc_fingerprint_differs_from_the_bare_config_fingerprint():
    # It must stay distinct from the config fingerprint the timeseries workflow stores, so recalc rows never
    # leak into the timeseries read (which filters by the bare config fingerprint).
    config_fp = "b" * 64
    assert compute_recalc_fingerprint(config_fp) != config_fp


def test_recalc_fingerprint_differs_per_config():
    assert compute_recalc_fingerprint("c" * 64) != compute_recalc_fingerprint("d" * 64)


def test_recalc_fingerprint_is_sha256_hex_length():
    assert len(compute_recalc_fingerprint("e" * 64)) == 64


def _stored_result(samples: int) -> dict[str, Any]:
    return {"baseline": {"key": "control", "number_of_samples": samples}, "variant_results": []}


def _samples(row: ExperimentMetricResult | None) -> list[int]:
    return [row.result["baseline"]["number_of_samples"]] if row is not None and row.result else []


class TestMetricResultStore(BaseTest):
    def _experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="store-flag", name="store")
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="store",
            start_date=_START,
            metrics=[
                {
                    "uuid": "m1",
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "purchase"},
                }
            ],
        )

    def _row(
        self, experiment: Experiment, fingerprint: str, *, query_to: datetime, completed_at: datetime, samples: int
    ) -> None:
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="m1",
            fingerprint=fingerprint,
            query_from=_START,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result=_stored_result(samples),
            completed_at=completed_at,
        )

    def _read(self, reader: str, experiment: Experiment, calculation_config: MetricCalculationConfig) -> list[int]:
        store = MetricResultStore(experiment_id=experiment.id)
        key = calculation_config.calculation_key()
        match reader:
            case "for_run":
                run = ExperimentMetricsRecalculation.objects.create(
                    team=self.team, experiment=experiment, metric_uuids=["m1"], query_to=_WINDOW
                )
                return [sample for row in store.for_run(run) for sample in _samples(row)]
            case "latest_daily_point":
                return _samples(
                    store.latest_daily_point(calculation_config, since=_WINDOW - timedelta(days=1), until=_WINDOW)
                )
            case "timeseries":
                return _samples(store.timeseries("m1", key, timezone=ZoneInfo("UTC")).by_day.get(_WINDOW_DAY))
            case "last_completed":
                return _samples(store.last_completed("m1"))
            case "previous_completed":
                return _samples(store.previous_completed("m1", key, before=_WINDOW + timedelta(days=1)))
            case "current_outcomes":
                summary = MetricResultStore.current_outcomes({experiment.id: "m1"})[experiment.id]
                assert summary.baseline_samples is not None
                return [int(summary.baseline_samples)]
        raise AssertionError(f"unknown reader {reader}")

    @parameterized.expand(
        [
            (f"{reader}_{tie}", reader, tie)
            for reader in (
                "for_run",
                "latest_daily_point",
                "timeseries",
                "last_completed",
                "previous_completed",
                "current_outcomes",
            )
            for tie in ("newer_write_wins", "higher_id_wins_between_equal_writes")
        ]
    )
    def test_rows_sharing_a_window_resolve_to_the_newest_write(self, _name: str, reader: str, tie: str) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        fingerprint = (
            compute_recalc_fingerprint(calculation_config.calculation_key())
            if reader == "for_run"
            else calculation_config.calculation_key()
        )
        # The unique constraint allows one row per (experiment, metric_uuid, query_to). Dropping it inside the
        # test transaction lets two rows share a window, and the rollback at the end of the test restores it.
        assert connection.in_atomic_block
        with connection.schema_editor() as editor:
            editor.alter_unique_together(ExperimentMetricResult, [("experiment", "metric_uuid", "query_to")], [])
        if tie == "newer_write_wins":
            # The newer write gets the lower id, so an order on id alone picks the wrong row.
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=2), samples=2)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
        else:
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=2)

        assert self._read(reader, experiment, calculation_config) == [2]

    def test_the_latest_window_inside_a_day_stands_for_that_day(self) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        key = calculation_config.calculation_key()
        # Both windows fall on 9 January. The later window was written first, so the write time alone picks the
        # other row.
        self._row(experiment, key, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=2)
        self._row(
            experiment, key, query_to=_WINDOW - timedelta(hours=6), completed_at=_WINDOW + timedelta(hours=2), samples=1
        )

        timeseries = MetricResultStore(experiment_id=experiment.id).timeseries("m1", key, timezone=ZoneInfo("UTC"))

        assert list(timeseries.by_day) == [_WINDOW_DAY]
        assert _samples(timeseries.by_day[_WINDOW_DAY]) == [2]

    @parameterized.expand([("own_team", True), ("other_team", False)])
    def test_previous_completed_metric_result_reads_only_the_callers_team(self, _name: str, own_team: bool) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        key = calculation_config.calculation_key()
        self._row(experiment, key, query_to=_WINDOW, completed_at=_WINDOW, samples=7)

        result = previous_completed_metric_result(
            experiment.id,
            team_id=self.team.id if own_team else self.team.id + 1,
            metric_uuid="m1",
            calculation_key=key,
            before=_WINDOW + timedelta(days=1),
        )

        assert result == (_stored_result(7) if own_team else None)
