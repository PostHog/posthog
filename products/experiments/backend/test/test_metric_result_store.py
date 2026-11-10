from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.schema import ExperimentQuery

from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_calculation.config import (
    CALCULATION_KEY_V2_FLAG,
    MetricCalculationConfig,
    get_metric_calculation_config,
)
from products.experiments.backend.metric_calculation.results import (
    MetricResultStore,
    _recalc_fingerprint,
    previous_completed_metric_result,
    record_daily_metric_result,
    result_configuration_status,
)
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.test.utils import patch_calculation_key_version
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
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch_calculation_key_version(2))

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
        self,
        experiment: Experiment,
        fingerprint: str,
        *,
        query_to: datetime,
        completed_at: datetime,
        samples: int,
        display_key: str | None = None,
        status: str = ExperimentMetricResult.Status.COMPLETED,
    ) -> ExperimentMetricResult:
        return ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="m1",
            fingerprint=fingerprint,
            display_key=display_key,
            query_from=_START,
            query_to=query_to,
            status=status,
            result=_stored_result(samples),
            completed_at=completed_at,
        )

    def _read(self, reader: str, experiment: Experiment, calculation_config: MetricCalculationConfig) -> list[int]:
        """The samples of the row a reader returns at _WINDOW."""
        store = MetricResultStore(experiment_id=experiment.id)
        match reader:
            case "for_run":
                run = ExperimentMetricsRecalculation.objects.create(
                    team=self.team,
                    experiment=experiment,
                    metric_uuids=["m1"],
                    query_to=_WINDOW,
                    status=ExperimentMetricsRecalculation.Status.COMPLETED,
                    completed_at=django_timezone.now(),
                )
                return [sample for row in store.for_run(run) for sample in _samples(row)]
            case "latest_daily_point":
                return _samples(
                    store.latest_daily_point(calculation_config, since=_WINDOW - timedelta(days=1), until=_WINDOW)
                )
            case "timeseries":
                return _samples(store.timeseries(calculation_config, timezone=ZoneInfo("UTC")).by_day.get(_WINDOW_DAY))
            case "previous_completed":
                return _samples(
                    store.previous_completed(
                        "m1",
                        [calculation_config.calculation_key(), calculation_config.legacy_key()],
                        display_key=calculation_config.legacy_key(),
                        before=_WINDOW + timedelta(days=1),
                    )
                )
            case "current_outcome":
                summary = store.current_outcome(calculation_config)
                assert summary is not None and summary.baseline_samples is not None
                return [int(summary.baseline_samples)]
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
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        fingerprint = (
            _recalc_fingerprint(calculation_config.calculation_key())
            if reader == "for_run"
            else calculation_config.calculation_key()
        )
        self._allow_rows_sharing_a_window()
        if tie == "newer_write_wins":
            # The newer write gets the lower id, so an order on id alone picks the wrong row.
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=2), samples=2)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
        else:
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=1)
            self._row(experiment, fingerprint, query_to=_WINDOW, completed_at=_WINDOW + timedelta(hours=1), samples=2)

        assert self._read(reader, experiment, calculation_config) == [2]

    @parameterized.expand(
        [
            *(
                (f"{reader}_{case}", reader, case)
                for reader in ("for_run", "latest_daily_point", "timeseries", "current_outcome")
                for case in ("only_a_version_1_row", "a_version_2_row_covers_it")
            ),
            *(
                (f"{reader}_{case}", reader, case)
                for reader in ("latest_daily_point", "current_outcome")
                # After a return to version 1, newer version 2 rows of the same settings must not hide behind an
                # older version 1 row. Under version 2, a backfill of past days must not hide the newer end-date row.
                for case in ("rolled_back_with_a_newer_version_2_row", "a_newer_version_1_row_than_the_version_2_row")
            ),
        ]
    )
    def test_a_version_1_row_stands_in_only_where_no_version_2_row_covers_it(
        self, _name: str, reader: str, case: str
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        salt = _recalc_fingerprint if reader == "for_run" else (lambda key: key)
        version_1_window, version_2_window = {
            "rolled_back_with_a_newer_version_2_row": (_WINDOW - timedelta(days=1), _WINDOW),
            "a_newer_version_1_row_than_the_version_2_row": (_WINDOW, _WINDOW - timedelta(days=1)),
        }.get(case, (_WINDOW, _WINDOW))
        self._allow_rows_sharing_a_window()
        if case != "only_a_version_1_row":
            self._row(
                experiment,
                salt(calculation_config.key_for_version(2)),
                display_key=salt(calculation_config.legacy_key()),
                query_to=version_2_window,
                completed_at=version_2_window,
                samples=2,
            )
        # On a shared window the version 1 row is the newer write, so only the key family keeps it behind the
        # version 2 row.
        self._row(
            experiment,
            salt(calculation_config.legacy_key()),
            query_to=version_1_window,
            completed_at=version_1_window,
            samples=1,
        )
        active_version = 1 if case == "rolled_back_with_a_newer_version_2_row" else 2

        expected = [1] if case in ("only_a_version_1_row", "a_newer_version_1_row_than_the_version_2_row") else [2]
        assert self._read(reader, experiment, calculation_config.with_key_version(active_version)) == expected

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

        timeseries = MetricResultStore(experiment_id=experiment.id).timeseries(
            calculation_config, timezone=ZoneInfo("UTC")
        )

        assert list(timeseries.by_day) == [_WINDOW_DAY]
        assert _samples(timeseries.by_day[_WINDOW_DAY]) == [2]

    def test_the_current_outcome_is_the_row_whose_data_ends_last(self) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        key = calculation_config.calculation_key()
        # A backfill that ran at 10:00 on 9 January stamps that day with the end of the day.
        self._row(experiment, key, query_to=_WINDOW, completed_at=_WINDOW - timedelta(hours=14), samples=1)
        # A recalculation run at 14:00 on the same day holds newer data under an earlier query_to.
        self._row(
            experiment,
            _recalc_fingerprint(key),
            query_to=_WINDOW - timedelta(hours=10),
            completed_at=_WINDOW - timedelta(hours=9, minutes=55),
            samples=2,
        )
        # A backfill of 8 January written after both, so the write time alone picks it.
        self._row(
            experiment, key, query_to=_WINDOW - timedelta(days=1), completed_at=_WINDOW - timedelta(hours=9), samples=3
        )

        assert self._read("current_outcome", experiment, calculation_config) == [2]

    @parameterized.expand(
        [("without_a_current_row", False, 1), ("with_a_current_row_whose_data_ends_as_late", True, 2)]
    )
    def test_a_batch_outcome_ranks_each_experiment_by_its_own_keys(
        self, _name: str, tied_current_row: bool, expected_samples: int
    ) -> None:
        earlier_stats = {"method": "bayesian", "bayesian": {"ci_level": 0.9}}
        experiment = self._experiment()
        experiment.stats_config = earlier_stats
        experiment.save()
        earlier_config = get_metric_calculation_config(experiment, "m1")
        assert earlier_config is not None
        self._row(
            experiment,
            earlier_config.calculation_key(),
            display_key=earlier_config.legacy_key(),
            query_to=_WINDOW,
            completed_at=_WINDOW + timedelta(minutes=30),
            samples=1,
        )
        experiment.stats_config = {"method": "bayesian", "bayesian": {"ci_level": 0.99}}
        experiment.save()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        if tied_current_row:
            # Its data ends at _WINDOW too, and the earlier row is the newer write, so only the experiment's own
            # current key breaks the tie.
            self._row(
                experiment,
                calculation_config.calculation_key(),
                query_to=_WINDOW + timedelta(hours=1),
                completed_at=_WINDOW,
                samples=2,
            )
        # Another experiment on the same flag and start date now has the first experiment's earlier settings.
        other = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=experiment.feature_flag,
            name="other",
            start_date=_START,
            metrics=experiment.metrics,
            stats_config=earlier_stats,
        )
        other_config = get_metric_calculation_config(other, "m1")
        assert other_config is not None and other_config.calculation_key() == earlier_config.calculation_key()

        outcome = MetricResultStore.current_outcomes({experiment.id: calculation_config, other.id: other_config})[
            experiment.id
        ]

        assert outcome.baseline_samples is not None
        assert int(outcome.baseline_samples) == expected_samples

    @parameterized.expand(
        [
            ("own_team", True, [("version_2", _WINDOW, 7)], 7),
            ("other_team", False, [("version_2", _WINDOW, 7)], None),
            ("only_a_point_from_before_the_conversion", True, [("version_1", _WINDOW, 7)], 7),
            ("only_a_point_under_earlier_settings", True, [("earlier_settings", _WINDOW, 7)], 7),
            (
                "the_newest_point_under_earlier_settings_wins",
                True,
                [("version_2", _WINDOW - timedelta(days=1), 5), ("earlier_settings", _WINDOW, 7)],
                7,
            ),
            (
                "the_newest_point_under_the_other_key_version_wins",
                True,
                [("version_2", _WINDOW - timedelta(days=1), 5), ("version_1", _WINDOW, 7)],
                7,
            ),
        ]
    )
    def test_previous_completed_metric_result(
        self, _name: str, own_team: bool, points: list[tuple[str, datetime, int]], expected_samples: int | None
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        for family, query_to, samples in points:
            fingerprint = {
                "version_2": calculation_config.calculation_key(),
                "version_1": calculation_config.legacy_key(),
                "earlier_settings": "key-of-the-earlier-team-settings",
            }[family]
            display_key = calculation_config.legacy_key() if family == "earlier_settings" else None
            self._row(
                experiment,
                fingerprint,
                display_key=display_key,
                query_to=query_to,
                completed_at=query_to,
                samples=samples,
            )

        result = previous_completed_metric_result(
            experiment.id,
            team_id=self.team.id if own_team else self.team.id + 1,
            metric_uuid="m1",
            calculation_key=calculation_config.calculation_key(),
            before=_WINDOW + timedelta(days=1),
        )

        assert result == (_stored_result(expected_samples) if expected_samples is not None else None)

    @parameterized.expand(
        [
            (f"{change}_{stopped}", change, history_shown, stopped)
            for change, history_shown in [("team", True), ("team_config", True), ("metric", False)]
            for stopped in [False, True]
        ]
    )
    def test_a_settings_change_keeps_the_history_that_the_experiment_still_describes(
        self, _name: str, change: str, history_shown: bool, stopped: bool
    ) -> None:
        experiment = self._experiment()
        if stopped:
            experiment.end_date = _WINDOW + timedelta(hours=1)
            experiment.save()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        store = MetricResultStore(experiment_id=experiment.id)
        store.record_daily_point(
            "m1",
            calculation_config.calculation_key(),
            display_key=calculation_config.legacy_key(),
            window=_WINDOW,
            query_from=_START,
            result=_stored_result(3),
        )
        run_window = _WINDOW + timedelta(hours=1)
        run = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=experiment,
            metric_uuids=["m1"],
            query_to=run_window,
            status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
        )
        store.record_run_result(
            str(run.id),
            calculation_config,
            window=run_window,
            query_from=_START,
            result=_stored_result(4),
            query_id=None,
        )
        ExperimentMetricsRecalculation.objects.filter(id=run.id).update(
            status=ExperimentMetricsRecalculation.Status.COMPLETED, completed_at=django_timezone.now()
        )

        if change == "team":
            self.team.test_account_filters = [{"key": "email", "type": "person", "value": "@example.com"}]
            self.team.save()
        elif change == "team_config":
            config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
            config.default_cuped_enabled = True
            config.save()
        else:
            experiment.metrics = [
                {
                    "uuid": "m1",
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "signup"},
                }
            ]
            experiment.save()
        experiment = Experiment.objects.get(pk=experiment.pk)
        changed_config = get_metric_calculation_config(experiment, "m1")
        assert changed_config is not None and changed_config.calculation_key() != calculation_config.calculation_key()

        series = store.timeseries(changed_config, timezone=ZoneInfo("UTC"))
        outcome = store.current_outcome(changed_config)
        shown = (_samples(series.by_day.get(_WINDOW_DAY)), outcome and outcome.baseline_samples)
        assert shown == (([3], "4") if history_shown else ([], None))
        assert not store.has_completed(changed_config, window=run_window)
        stored_run = ExperimentMetricsRecalculation.objects.get(id=run.id)
        run_rows = store.for_run(stored_run)
        if stopped and history_shown:
            assert result_configuration_status(run_rows[0].fingerprint, changed_config) == "previous"
        assert [sample for row in run_rows for sample in _samples(row)] == ([4] if stopped and history_shown else [])
        assert store.latest_daily_point(changed_config, since=_WINDOW - timedelta(days=1), until=_WINDOW) is None
        if history_shown:
            assert series.configuration_by_day[_WINDOW_DAY] == "previous"
            assert outcome is not None and outcome.configuration_status == "previous"
        preserved = store.latest_daily_point(changed_config, since=_START, until=_WINDOW, preserve_history=stopped)
        assert _samples(preserved) == ([3] if stopped and history_shown else [])

    def test_legacy_result_is_displayable_but_not_reusable(self) -> None:
        experiment = self._experiment()
        config = get_metric_calculation_config(experiment, "m1")
        assert config is not None
        self._row(
            experiment, _recalc_fingerprint(config.legacy_key()), query_to=_WINDOW, completed_at=_WINDOW, samples=7
        )
        run = self._run(experiment, ExperimentMetricsRecalculation.Status.COMPLETED)
        [row] = MetricResultStore(experiment_id=experiment.id).for_run(run)
        assert (_samples(row), result_configuration_status(row.fingerprint, config)) == ([7], "unknown")
        assert not MetricResultStore(experiment_id=experiment.id).has_completed(config, window=_WINDOW)

    def test_daily_facades_use_the_already_resolved_display_key(self) -> None:
        experiment = self._experiment()
        config = get_metric_calculation_config(experiment, "m1")
        assert config is not None
        with self.assertNumQueries(6):
            record_daily_metric_result(
                experiment.id,
                metric_uuid="m1",
                calculation_key=config.calculation_key(),
                display_key=config.legacy_key(),
                window=_WINDOW,
                query_from=_START,
                result=_stored_result(3),
            )
        with self.assertNumQueries(2):
            result = previous_completed_metric_result(
                experiment.id,
                team_id=self.team.id,
                metric_uuid="m1",
                calculation_key=config.calculation_key(),
                display_key=config.legacy_key(),
                before=_WINDOW + timedelta(days=1),
            )
        assert result == _stored_result(3)

    def _run(self, experiment: Experiment, status: str) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(
            team=self.team, experiment=experiment, metric_uuids=["m1"], status=status, query_to=_WINDOW
        )

    def _write(self, writer: str, experiment: Experiment, calculation_config: MetricCalculationConfig) -> None:
        store = MetricResultStore(experiment_id=experiment.id)
        key = calculation_config.calculation_key()
        match writer:
            case "run_result":
                run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
                store.record_run_result(
                    str(run.id),
                    calculation_config,
                    window=_WINDOW,
                    query_from=_START,
                    result=_stored_result(9),
                    query_id="q",
                )
            case "run_failure":
                run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
                store.record_run_failure(
                    str(run.id),
                    calculation_config,
                    window=_WINDOW,
                    query_from=_START,
                    error_message="boom",
                    query_id="q",
                )
            case "daily_point":
                store.record_daily_point(
                    "m1",
                    key,
                    display_key=calculation_config.legacy_key(),
                    window=_WINDOW,
                    query_from=_START,
                    result=_stored_result(9),
                )
            case "daily_failure":
                store.record_daily_failure(
                    "m1",
                    key,
                    display_key=calculation_config.legacy_key(),
                    window=_WINDOW,
                    query_from=_START,
                    error_message="boom",
                )
            case "daily_metric_result":
                record_daily_metric_result(
                    experiment.id,
                    metric_uuid="m1",
                    calculation_key=key,
                    display_key=calculation_config.legacy_key(),
                    window=_WINDOW,
                    query_from=_START,
                    result=_stored_result(9),
                )
            case "sync_copy":
                point = ExperimentMetricResult(fingerprint=key, result=_stored_result(9))
                store.copy_into_sync_run(
                    _WINDOW, [(calculation_config, point)], query_from=_START, completed_at=_WINDOW
                )
            case _:
                raise AssertionError(f"unknown writer {writer}")

    @parameterized.expand(
        [
            ("run_result", True, ExperimentMetricResult.Status.COMPLETED),
            ("run_failure", True, ExperimentMetricResult.Status.FAILED),
            ("daily_point", False, ExperimentMetricResult.Status.COMPLETED),
            ("daily_failure", False, ExperimentMetricResult.Status.FAILED),
            ("daily_metric_result", False, ExperimentMetricResult.Status.COMPLETED),
            ("sync_copy", True, ExperimentMetricResult.Status.COMPLETED),
        ]
    )
    def test_a_write_takes_over_the_row_that_holds_its_window_under_another_fingerprint(
        self, writer: str, salted: bool, status: str
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        self._row(experiment, "another-fingerprint", query_to=_WINDOW, completed_at=_WINDOW, samples=1, status=status)

        self._write(writer, experiment, calculation_config)

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        salt = _recalc_fingerprint if salted else (lambda key: key)
        assert (row.fingerprint, row.display_key) == (
            salt(calculation_config.calculation_key()),
            salt(calculation_config.legacy_key()),
        )
        assert row.status == status
        if status == ExperimentMetricResult.Status.COMPLETED:
            assert (row.result, row.error_message) == (_stored_result(9), None)
        else:
            assert (row.result, row.error_message, row.completed_at) == (None, "boom", None)

    @parameterized.expand(
        [
            (
                f"{writer}_{held_by}",
                writer,
                held_by,
                reader,
                (writer, held_by) != ("daily_failure", "the_same_daily_key"),
            )
            for writer in ("run_failure", "daily_failure")
            for held_by, reader in (
                ("a_version_1_recalculation", "for_run"),
                ("the_same_recalculation_key", "for_run"),
                ("a_version_1_daily_point", "timeseries"),
                ("the_same_daily_key", "timeseries"),
            )
        ]
    )
    def test_only_a_daily_failure_replaces_a_completed_row_and_only_under_its_own_key(
        self, _name: str, writer: str, held_by: str, reader: str, kept: bool
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        held_fingerprint = {
            "a_version_1_recalculation": _recalc_fingerprint(calculation_config.key_for_version(1)),
            "the_same_recalculation_key": _recalc_fingerprint(calculation_config.calculation_key()),
            "a_version_1_daily_point": calculation_config.key_for_version(1),
            "the_same_daily_key": calculation_config.calculation_key(),
        }[held_by]
        self._row(experiment, held_fingerprint, query_to=_WINDOW, completed_at=_WINDOW, samples=1)

        self._write(writer, experiment, calculation_config)

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        if kept:
            assert (row.fingerprint, row.status, row.error_message) == (
                held_fingerprint,
                ExperimentMetricResult.Status.COMPLETED,
                None,
            )
            assert self._read(reader, experiment, calculation_config) == [1]
        else:
            assert (row.fingerprint, row.status, row.result, row.error_message) == (
                held_fingerprint,
                ExperimentMetricResult.Status.FAILED,
                None,
                "boom",
            )

    @parameterized.expand(
        [
            (ExperimentMetricsRecalculation.Status.FAILED,),
            (ExperimentMetricsRecalculation.Status.COMPLETED,),
            (None,),
        ]
    )
    def test_a_run_write_skips_a_terminal_or_missing_recalculation(self, status: str | None) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        run = self._run(experiment, ExperimentMetricsRecalculation.Status.IN_PROGRESS)
        if status is None:
            ExperimentMetricsRecalculation.objects.filter(id=run.id).delete()
        else:
            ExperimentMetricsRecalculation.objects.filter(id=run.id).update(status=status)
        self._row(experiment, "fingerprint-from-the-superseding-run", query_to=_WINDOW, completed_at=_WINDOW, samples=1)

        # A failure never replaces a completed row, so only a result write needs the terminal-run guard.
        stored = MetricResultStore(experiment_id=experiment.id).record_run_result(
            str(run.id),
            calculation_config,
            window=_WINDOW,
            query_from=_START,
            result=_stored_result(9),
            query_id=None,
        )

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        assert (stored, row.fingerprint, _samples(row)) == (False, "fingerprint-from-the-superseding-run", [1])


def _patch_key_version_flag(state: bool | None | Exception) -> AbstractContextManager[Any]:
    def feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool | None:
        if flag_key != CALCULATION_KEY_V2_FLAG:
            return False
        if isinstance(state, Exception):
            raise state
        return state

    return patch("posthoganalytics.feature_enabled", side_effect=feature_enabled)


class TestCalculationKeyActivation(BaseTest):
    def _experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="key-version-flag")
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="key version",
            start_date=_START,
            metrics=[
                {
                    "uuid": "m1",
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
        )

    def _runner(self, experiment: Experiment) -> ExperimentQueryRunner:
        assert experiment.metrics is not None
        query = ExperimentQuery(experiment_id=experiment.id, metric=build_metric(experiment.metrics[0]))
        return ExperimentQueryRunner(query=query, team=self.team)

    @parameterized.expand(
        [
            ("flag_off", False, 1),
            ("inconclusive_local_evaluation", None, 1),
            ("evaluation_error", RuntimeError("flag definitions unavailable"), 1),
            ("flag_on", True, 2),
        ]
    )
    def test_the_team_flag_decides_the_key_and_the_query_cache_payload(
        self, _name: str, flag_state: bool | None | Exception, expected_version: int
    ) -> None:
        experiment = self._experiment()
        with _patch_key_version_flag(flag_state):
            calculation_config = get_metric_calculation_config(experiment, "m1")
            payload = self._runner(experiment).get_cache_payload()
        assert calculation_config is not None
        assert calculation_config.calculation_key() == calculation_config.key_for_version(expected_version)
        # A new payload field would miss every cached experiment response, so version 1 keeps the payload as it was.
        assert payload.get("calculation_key") == (
            calculation_config.calculation_key() if expected_version == 2 else None
        )

    @parameterized.expand(
        [
            ("confidence", {"bayesian": {"ci_level": 0.9}}),
            ("cuped", {"cuped": {"enabled": True}}),
            ("multiple_variants", {"multiple_variant_handling": "first_seen"}),
            ("test_accounts", None),
        ]
    )
    def test_query_cache_key_changes_with_analytical_settings_under_version_2(
        self, _name: str, stats_config: dict | None
    ) -> None:
        experiment = self._experiment()
        with _patch_key_version_flag(True):
            before = self._runner(experiment).get_cache_key()
            if stats_config is None:
                self.team.test_account_filters = [{"key": "email", "type": "person", "value": "@example.com"}]
                self.team.save()
            elif _name == "multiple_variants":
                experiment.exposure_criteria = stats_config
                experiment.save()
            else:
                experiment.stats_config = stats_config
                experiment.save()
            after = self._runner(experiment).get_cache_key()
        assert before != after
