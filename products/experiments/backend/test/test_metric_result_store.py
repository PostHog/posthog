from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from django.db import connection
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.schema import ExperimentQuery

from posthog.models import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    get_metric_calculation_config,
)
from products.experiments.backend.metric_calculation.results import (
    MetricResultStore,
    _recalc_fingerprint,
    previous_completed_metric_result,
    record_daily_metric_result,
)
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.recalculation import get_run_results
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
        self,
        experiment: Experiment,
        fingerprint: str,
        *,
        query_to: datetime,
        completed_at: datetime,
        samples: int,
        display_key: str | None = None,
    ) -> ExperimentMetricResult:
        return ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="m1",
            fingerprint=fingerprint,
            display_key=display_key,
            query_from=_START,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
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
                        calculation_config.calculation_key(),
                        legacy_key=calculation_config.legacy_key(),
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
            (f"{reader}_{case}", reader, case)
            for reader in ("for_run", "latest_daily_point", "timeseries", "previous_completed", "current_outcome")
            for case in ("only_a_version_1_row", "a_version_2_row_covers_it")
        ]
    )
    def test_a_version_1_row_stands_in_only_where_no_version_2_row_covers_it(
        self, _name: str, reader: str, case: str
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        salt = _recalc_fingerprint if reader == "for_run" else (lambda key: key)
        self._allow_rows_sharing_a_window()
        # The version 1 row is the newer write, so only the key family keeps it behind the version 2 row.
        self._row(experiment, salt(calculation_config.legacy_key()), query_to=_WINDOW, completed_at=_WINDOW, samples=1)
        if case == "a_version_2_row_covers_it":
            self._row(
                experiment,
                salt(calculation_config.calculation_key()),
                query_to=_WINDOW,
                completed_at=_WINDOW - timedelta(hours=1),
                samples=2,
            )

        expected = [2] if case == "a_version_2_row_covers_it" else [1]
        assert self._read(reader, experiment, calculation_config) == expected

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

    @parameterized.expand([("without_a_current_row", False, 1), ("with_an_older_current_row", True, 2)])
    def test_a_batch_outcome_ranks_each_experiment_by_its_own_keys(
        self, _name: str, older_current_row: bool, expected_samples: int
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
            completed_at=_WINDOW,
            samples=1,
        )
        experiment.stats_config = {"method": "bayesian", "bayesian": {"ci_level": 0.99}}
        experiment.save()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        if older_current_row:
            day_before = _WINDOW - timedelta(days=1)
            self._row(
                experiment,
                calculation_config.calculation_key(),
                query_to=day_before,
                completed_at=day_before,
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
                "an_older_version_2_point_wins",
                True,
                [("version_2", _WINDOW - timedelta(days=1), 5), ("earlier_settings", _WINDOW, 7)],
                5,
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
            calculation_config=calculation_config,
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
            assert get_run_results(stored_run)[0]["configuration_status"] == "previous"
        assert [sample for row in run_rows for sample in _samples(row)] == ([4] if stopped and history_shown else [])
        assert store.latest_daily_point(changed_config, since=_WINDOW - timedelta(days=1), until=_WINDOW) is None
        if history_shown:
            assert series.configuration_by_day[_WINDOW_DAY] == "previous"
            assert outcome is not None and outcome.configuration_status == "previous"
        preserved = store.latest_daily_point(changed_config, since=_START, until=_WINDOW, preserve_history=stopped)
        assert _samples(preserved) == ([3] if stopped and history_shown else [])

    @parameterized.expand(
        [
            ("confidence", {"bayesian": {"ci_level": 0.9}}),
            ("cuped", {"cuped": {"enabled": True}}),
            ("multiple_variants", {"multiple_variant_handling": "first_seen"}),
            ("test_accounts", None),
        ]
    )
    def test_query_cache_key_changes_with_analytical_settings(self, _name: str, stats_config: dict | None) -> None:
        experiment = self._experiment()
        assert experiment.metrics is not None
        query = ExperimentQuery(experiment_id=experiment.id, metric=build_metric(experiment.metrics[0]))
        before = ExperimentQueryRunner(query=query, team=self.team).get_cache_key()
        if stats_config is None:
            self.team.test_account_filters = [{"key": "email", "type": "person", "value": "@example.com"}]
            self.team.save()
        elif _name == "multiple_variants":
            experiment.exposure_criteria = stats_config
            experiment.save()
        else:
            experiment.stats_config = stats_config
            experiment.save()
        after = ExperimentQueryRunner(query=query, team=self.team).get_cache_key()
        assert before != after

    def test_legacy_result_is_displayable_but_not_reusable(self) -> None:
        experiment = self._experiment()
        config = get_metric_calculation_config(experiment, "m1")
        assert config is not None
        self._row(
            experiment, _recalc_fingerprint(config.legacy_key()), query_to=_WINDOW, completed_at=_WINDOW, samples=7
        )
        run = self._run(experiment, ExperimentMetricsRecalculation.Status.COMPLETED)
        assert get_run_results(run)[0]["configuration_status"] == "unknown"
        assert not MetricResultStore(experiment_id=experiment.id).has_completed(config, window=_WINDOW)

    def test_daily_facades_use_the_already_resolved_display_key(self) -> None:
        experiment = self._experiment()
        config = get_metric_calculation_config(experiment, "m1")
        assert config is not None
        with self.assertNumQueries(6):
            record_daily_metric_result(
                experiment.id,
                team_id=self.team.id,
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
                    calculation_config=calculation_config,
                    window=_WINDOW,
                    query_from=_START,
                    result=_stored_result(9),
                )
            case "daily_failure":
                store.record_daily_failure(
                    "m1",
                    key,
                    calculation_config=calculation_config,
                    window=_WINDOW,
                    query_from=_START,
                    error_message="boom",
                )
            case "daily_metric_result":
                record_daily_metric_result(
                    experiment.id,
                    team_id=self.team.id,
                    metric_uuid="m1",
                    calculation_key=key,
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
        self._row(experiment, "another-fingerprint", query_to=_WINDOW, completed_at=_WINDOW, samples=1)

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

    @parameterized.expand([("another_team",), ("stale_key",)])
    def test_a_daily_write_resolves_no_display_key_outside_its_team_or_under_a_stale_key(self, cause: str) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        team_id = Team.objects.create(organization=self.organization).id if cause == "another_team" else self.team.id
        key = (
            "key-of-the-configuration-before-an-edit" if cause == "stale_key" else calculation_config.calculation_key()
        )

        record_daily_metric_result(
            experiment.id,
            team_id=team_id,
            metric_uuid="m1",
            calculation_key=key,
            window=_WINDOW,
            query_from=_START,
            result=_stored_result(9),
        )

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        assert (row.fingerprint, row.display_key) == (key, None)

    @parameterized.expand([("held_by_a_recalculation", True), ("held_by_the_same_daily_key", False)])
    def test_a_daily_failure_replaces_a_completed_row_only_under_its_own_key(
        self, _name: str, held_by_recalculation: bool
    ) -> None:
        experiment = self._experiment()
        calculation_config = get_metric_calculation_config(experiment, "m1")
        assert calculation_config is not None
        key = calculation_config.calculation_key()
        held_fingerprint = _recalc_fingerprint(key) if held_by_recalculation else key
        self._row(experiment, held_fingerprint, query_to=_WINDOW, completed_at=_WINDOW, samples=1)

        self._write("daily_failure", experiment, calculation_config)

        row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid="m1", query_to=_WINDOW)
        if held_by_recalculation:
            assert (row.fingerprint, row.status, _samples(row)) == (
                held_fingerprint,
                ExperimentMetricResult.Status.COMPLETED,
                [1],
            )
            assert self._read("for_run", experiment, calculation_config) == [1]
        else:
            assert (row.fingerprint, row.status, row.result, row.error_message) == (
                key,
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

        MetricResultStore(experiment_id=experiment.id).record_run_failure(
            str(run.id),
            calculation_config,
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
