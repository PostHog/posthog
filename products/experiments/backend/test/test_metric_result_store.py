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

    def _read(self, reader: str, experiment: Experiment, spec: CalculationSpec) -> tuple[list[int], bool]:
        """The samples of the row a reader returns at _WINDOW, and whether it marks that row legacy."""
        store = MetricResultStore(experiment_id=experiment.id)
        match reader:
            case "for_run":
                run = ExperimentMetricsRecalculation.objects.create(
                    team=self.team, experiment=experiment, metric_uuids=["m1"], query_to=_WINDOW
                )
                stored = store.for_run(run)
                return [sample for item in stored for sample in _samples(item.row)], any(i.legacy for i in stored)
            case "latest_daily_point":
                point = store.latest_daily_point(
                    spec, since=_WINDOW - timedelta(days=1), until=_WINDOW, include_legacy=True
                )
                return (_samples(point.row), point.legacy) if point is not None else ([], False)
            case "timeseries":
                series = store.timeseries(spec, timezone=ZoneInfo("UTC"))
                return _samples(series.by_day.get(_WINDOW_DAY)), _WINDOW_DAY in series.legacy_days
            case "previous_completed":
                row = store.previous_completed("m1", spec.calculation_key(), before=_WINDOW + timedelta(days=1))
                return _samples(row), False
            case "current_outcome":
                summary = store.current_outcome(spec)
                assert summary is not None and summary.baseline_samples is not None
                return [int(summary.baseline_samples)], summary.legacy
        raise AssertionError(f"unknown reader {reader}")

    def _allow_rows_sharing_a_window(self) -> None:
        # The unique constraint allows one row per (experiment, metric_uuid, query_to). Dropping it inside the
        # test transaction lets two rows share a window, and the rollback at the end of the test restores it.
        assert connection.in_atomic_block
        with connection.schema_editor() as editor:
            editor.alter_unique_together(ExperimentMetricResult, [("experiment", "metric_uuid", "query_to")], [])

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
        self._allow_rows_sharing_a_window()
        if tie == "newer_write_wins":
            # The newer write gets the lower id, so an order on id alone picks the wrong row.
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=2), samples=2)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
        else:
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=2)

        assert self._read(reader, experiment, spec) == ([2], False)

    @parameterized.expand(
        [
            (f"{reader}_{case}", reader, case)
            for reader in ("for_run", "latest_daily_point", "timeseries", "current_outcome")
            for case in ("only_a_legacy_row", "a_current_row_covers_it")
        ]
    )
    def test_a_legacy_row_is_shown_only_where_no_current_row_covers_it(
        self, _name: str, reader: str, case: str
    ) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        salt = _recalc_fingerprint if reader == "for_run" else (lambda key: key)
        self._allow_rows_sharing_a_window()
        # The legacy row is the newer write, so only the key family keeps it behind the current row.
        self._row(experiment, salt(spec.legacy_key()), query_to=_WINDOW, completed_at=_WINDOW, samples=1)
        if case == "a_current_row_covers_it":
            self._row(
                experiment,
                salt(spec.calculation_key()),
                query_to=_WINDOW,
                completed_at=_WINDOW - timedelta(hours=1),
                samples=2,
            )

        expected = ([2], False) if case == "a_current_row_covers_it" else ([1], True)
        assert self._read(reader, experiment, spec) == expected

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

        timeseries = MetricResultStore(experiment_id=experiment.id).timeseries(spec, timezone=ZoneInfo("UTC"))

        assert list(timeseries.by_day) == [_WINDOW_DAY]
        assert _samples(timeseries.by_day[_WINDOW_DAY]) == [2]

    @parameterized.expand(
        [
            ("own_team", True, [("current", _WINDOW, 7)], 7),
            ("other_team", False, [("current", _WINDOW, 7)], None),
            # The first daily run under key version 2 compares with the point from before it.
            ("only_a_legacy_point", True, [("legacy", _WINDOW, 7)], 7),
            ("a_current_point_wins_over_a_newer_legacy_one", True, [("current", _START, 5), ("legacy", _WINDOW, 9)], 5),
        ]
    )
    def test_previous_completed_metric_result(
        self, _name: str, own_team: bool, points: list[tuple[str, datetime, int]], expected_samples: int | None
    ) -> None:
        experiment = self._experiment()
        spec = plan_metric(experiment, "m1")
        assert spec is not None
        for family, query_to, samples in points:
            key = spec.calculation_key() if family == "current" else spec.legacy_key()
            self._row(experiment, key, query_to=query_to, completed_at=query_to, samples=samples)

        result = previous_completed_metric_result(
            experiment.id,
            team_id=self.team.id if own_team else self.team.id + 1,
            metric_uuid="m1",
            calculation_key=spec.calculation_key(),
            before=_WINDOW + timedelta(days=1),
        )

        assert result == (_stored_result(expected_samples) if expected_samples is not None else None)

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
