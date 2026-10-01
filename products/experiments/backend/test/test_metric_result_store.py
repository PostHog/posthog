from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from django.db import connection

from parameterized import parameterized

from products.experiments.backend.metric_calculation.results import (
    MetricResultStore,
    _recalc_fingerprint,
    previous_completed_metric_result,
)
from products.experiments.backend.metric_calculation.spec import CalculationSpec, plan_metric
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
    assert _recalc_fingerprint(config_fp) == _recalc_fingerprint(config_fp)


def test_recalc_fingerprint_differs_from_the_bare_config_fingerprint():
    # It must stay distinct from the config fingerprint the timeseries workflow stores, so recalc rows never
    # leak into the timeseries read (which filters by the bare config fingerprint).
    config_fp = "b" * 64
    assert _recalc_fingerprint(config_fp) != config_fp


def test_recalc_fingerprint_differs_per_config():
    assert _recalc_fingerprint("c" * 64) != _recalc_fingerprint("d" * 64)


def test_recalc_fingerprint_is_sha256_hex_length():
    assert len(_recalc_fingerprint("e" * 64)) == 64


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

    def _read(self, reader: str, experiment: Experiment, spec: CalculationSpec) -> list[int]:
        store = MetricResultStore(experiment_id=experiment.id)
        key = spec.calculation_key()
        match reader:
            case "for_run":
                run = ExperimentMetricsRecalculation.objects.create(
                    team=self.team, experiment=experiment, metric_uuids=["m1"], query_to=_WINDOW
                )
                return [sample for row in store.for_run(run) for sample in _samples(row)]
            case "latest_daily_point":
                return _samples(store.latest_daily_point(spec, since=_WINDOW - timedelta(days=1), until=_WINDOW))
            case "timeseries":
                return _samples(store.timeseries("m1", key, timezone=ZoneInfo("UTC")).by_day.get(_WINDOW_DAY))
            case "previous_completed":
                return _samples(store.previous_completed("m1", key, before=_WINDOW + timedelta(days=1)))
            case "current_outcome":
                summary = store.current_outcome(spec)
                assert summary is not None and summary.baseline_samples is not None
                return [int(summary.baseline_samples)]
        raise AssertionError(f"unknown reader {reader}")

    @parameterized.expand(
        [
            (f"{reader}_{tie}", reader, tie)
            for reader in (
                "for_run",
                "latest_daily_point",
                "timeseries",
                "previous_completed",
                "current_outcome",
            )
            for tie in ("newer_write_wins", "higher_id_wins_between_equal_writes")
        ]
    )
    def test_rows_sharing_a_window_resolve_to_the_newest_write(self, _name: str, reader: str, tie: str) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        fingerprint = _recalc_fingerprint(spec.calculation_key()) if reader == "for_run" else spec.calculation_key()
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

        assert self._read(reader, experiment, spec) == [2]

    def test_the_latest_window_inside_a_day_stands_for_that_day(self) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        key = spec.calculation_key()
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
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        key = spec.calculation_key()
        self._row(experiment, key, query_to=_WINDOW, completed_at=_WINDOW, samples=7)

        result = previous_completed_metric_result(
            experiment.id,
            team_id=self.team.id if own_team else self.team.id + 1,
            metric_uuid="m1",
            calculation_key=key,
            before=_WINDOW + timedelta(days=1),
        )

        assert result == (_stored_result(7) if own_team else None)

    def _run(self, experiment: Experiment, status: str) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(
            team=self.team, experiment=experiment, metric_uuids=["m1"], status=status, query_to=_WINDOW
        )

    def _write(self, writer: str, experiment: Experiment, spec: CalculationSpec) -> None:
        store = MetricResultStore(experiment_id=experiment.id)
        key = spec.calculation_key()
        match writer:
            case "run_result":
                run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
                store.record_run_result(
                    str(run.id), spec, window=_WINDOW, query_from=_START, result=_stored_result(9), query_id="q"
                )
            case "run_failure":
                run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
                store.record_run_failure(
                    str(run.id), spec, window=_WINDOW, query_from=_START, error_message="boom", query_id="q"
                )
            case "daily_point":
                store.record_daily_point("m1", key, window=_WINDOW, query_from=_START, result=_stored_result(9))
            case "daily_failure":
                store.record_daily_failure("m1", key, window=_WINDOW, query_from=_START, error_message="boom")
            case "sync_copy":
                point = ExperimentMetricResult(result=_stored_result(9))
                store.copy_into_sync_run(_WINDOW, [(spec, point)], query_from=_START, completed_at=_WINDOW)
            case _:
                raise AssertionError(f"unknown writer {writer}")

    @parameterized.expand(
        [
            ("run_result", True, ExperimentMetricResult.Status.COMPLETED),
            ("run_failure", True, ExperimentMetricResult.Status.FAILED),
            ("daily_point", False, ExperimentMetricResult.Status.COMPLETED),
            ("daily_failure", False, ExperimentMetricResult.Status.FAILED),
            ("sync_copy", True, ExperimentMetricResult.Status.COMPLETED),
        ]
    )
    def test_a_write_takes_over_the_row_that_holds_its_window_under_another_fingerprint(
        self, writer: str, salted: bool, status: str
    ) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        self._row(experiment, "another-fingerprint", query_to=_WINDOW, completed_at=_WINDOW, samples=1)

        self._write(writer, experiment, spec)

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        key = spec.calculation_key()
        assert row.fingerprint == (_recalc_fingerprint(key) if salted else key)
        assert row.status == status
        if status == ExperimentMetricResult.Status.COMPLETED:
            assert (row.result, row.error_message) == (_stored_result(9), None)
        else:
            assert (row.result, row.error_message, row.completed_at) == (None, "boom", None)

    @parameterized.expand(
        [
            (ExperimentMetricsRecalculation.Status.FAILED,),
            (ExperimentMetricsRecalculation.Status.COMPLETED,),
            (None,),
        ]
    )
    def test_a_run_write_skips_a_terminal_or_missing_recalculation(self, status: str | None) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
        if status is None:
            ExperimentMetricsRecalculation.objects.filter(id=run.id).delete()
        else:
            ExperimentMetricsRecalculation.objects.filter(id=run.id).update(status=status)
        self._row(experiment, "fingerprint-from-the-superseding-run", query_to=_WINDOW, completed_at=_WINDOW, samples=1)

        MetricResultStore(experiment_id=experiment.id).record_run_failure(
            str(run.id),
            spec,
            window=_WINDOW,
            query_from=_START,
            error_message="the orphan's late failure",
            query_id=None,
        )

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        assert (row.fingerprint, row.status, row.error_message) == (
            "fingerprint-from-the-superseding-run",
            ExperimentMetricResult.Status.COMPLETED,
            None,
        )
