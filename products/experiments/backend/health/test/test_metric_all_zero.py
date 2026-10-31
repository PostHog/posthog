from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.event_definitions.backend.models import EventDefinition
from products.experiments.backend.facade.api import get_experiment_health
from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthReaderAccess,
)
from products.experiments.backend.health.checks.metric_all_zero import metric_all_zero
from products.experiments.backend.health.context import LatestCalculation, ZeroMetric
from products.experiments.backend.health.skips import CheckSkip
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT
from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.feature_flags.backend.models.feature_flag import FeatureFlag

CODE = ExperimentHealthFindingCode.METRIC_ALL_ZERO
WARNING = ExperimentHealthFindingSeverity.WARNING
INFO = ExperimentHealthFindingSeverity.INFO
NO_QUERIES = ExperimentHealthReaderAccess(
    can_read_flag_history=False, can_query_events=False, denied_event_properties=frozenset()
)
LAST_ARRIVED = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
MEAN = {"metric_type": "mean"}
BOUNDED = {"metric_type": "mean", "upper_bound_percentile": 0.99}


def _metric(**changes: Any) -> ZeroMetric:
    fields: dict[str, Any] = {
        "metric_id": "metric",
        "name": "Purchases",
        "role": "primary",
        "exposures": 20000,
        "ratio_side": None,
        "definition": MEAN,
        "reached_earlier_step": 0,
        "events": ("purchase",),
        "has_blank_event": False,
        "has_filters": False,
        "stopped_events": {},
    }
    return ZeroMetric(**{**fields, **changes})


def _outcome(
    *metrics: ZeroMetric, hours_of_data: float = 96, **changes: Any
) -> ExperimentHealthFinding | CheckSkip | None:
    calculation = LatestCalculation(
        metric_count=len(metrics) or 1,
        finished_at=LAST_ARRIVED,
        failures=(),
        completed_count=len(metrics),
        completed_exposures_paths=frozenset(),
        zero_metrics=metrics,
        hours_of_data=hours_of_data,
    )
    return metric_all_zero(replace(RUNNING_CONTEXT, latest_calculation=calculation, **changes))


def _variant(*, samples: int, total: float, squares: float | None = None, denominator: float | None = None) -> dict:
    return {
        "key": "test",
        "method": "bayesian",
        "number_of_samples": samples,
        "sum": total,
        "sum_squares": total**2 if squares is None else squares,
        "denominator_sum": denominator,
    }


def _result(*, samples: int, total: float, squares: float | None = None, denominator: float | None = None) -> dict:
    variant = _variant(samples=samples, total=total, squares=squares, denominator=denominator)
    baseline = {key: value for key, value in variant.items() if key != "method"}
    return {"baseline": {**baseline, "key": "control"}, "variant_results": [variant]}


class TestMetricAllZero(TestCase):
    @parameterized.expand(
        [
            ("reads_zero_with_the_usual_causes", _metric(), {}, (None, WARNING, "same ID as the exposure")),
            (
                "the_filters_of_the_metric",
                _metric(has_filters=True),
                {},
                (None, WARNING, "Check that the metric filters match"),
            ),
            (
                "an_earlier_funnel_step",
                _metric(reached_earlier_step=900),
                {},
                (None, WARNING, "900 reached an earlier step, but nobody finished the funnel."),
            ),
            ("a_side_of_a_ratio", _metric(ratio_side="numerator"), {}, (None, WARNING, "The numerator of the primary")),
            (
                "an_event_with_an_empty_name",
                _metric(has_blank_event=True, events=()),
                {},
                ("blank_event", WARNING, "matches no events"),
            ),
            (
                "an_event_that_stopped_before_launch",
                _metric(stopped_events={"purchase": LAST_ARRIVED}),
                {},
                ("event_stopped", WARNING, 'The event "purchase" last arrived on October 1, 2026 at 11:30 AM CEST'),
            ),
            (
                "an_outlier_bound_that_counts_zeros",
                _metric(definition=BOUNDED),
                {},
                ("outlier_bound", WARNING, "When fewer than 1% have a value, the bound is 0"),
            ),
            (
                "after_the_end_nobody_can_add_events",
                _metric(),
                ENDED,
                (None, INFO, "same ID as the exposure"),
            ),
            (
                "after_the_end_a_stopped_event_stays_info",
                _metric(stopped_events={"purchase": LAST_ARRIVED}),
                ENDED,
                ("event_stopped", INFO, "before the experiment started"),
            ),
            (
                "after_the_end_a_setting_still_brings_back_the_results",
                _metric(definition=BOUNDED),
                ENDED,
                ("outlier_bound", WARNING, "Turn on"),
            ),
            (
                "secondary_metrics_report_only_the_outlier_bound",
                _metric(role="secondary", definition=BOUNDED),
                {},
                ("outlier_bound", INFO, 'The secondary metric "Purchases"'),
            ),
        ]
    )
    def test_reports(
        self, _name: str, metric: ZeroMetric, changes: dict[str, Any], expected: tuple[str | None, Any, str]
    ) -> None:
        outcome = _outcome(metric, **changes)
        assert isinstance(outcome, ExperimentHealthFinding)
        subcode, severity, words = expected
        self.assertEqual((outcome.code, outcome.subcode, outcome.severity), (CODE, subcode, severity))
        self.assertIn(words, outcome.detail)

    @parameterized.expand(
        [
            ("under_the_exposures_floor", _metric(exposures=999), 96),
            ("under_the_data_floor", _metric(), 71),
            ("a_secondary_metric_without_a_bound", _metric(role="secondary"), 96),
            ("an_empty_event_name_on_a_secondary_metric", _metric(role="secondary", has_blank_event=True), 96),
            (
                "an_empty_event_name_is_no_bound",
                _metric(role="secondary", definition=BOUNDED, has_blank_event=True),
                96,
            ),
            ("a_bound_under_its_exposures_floor", _metric(definition=BOUNDED, exposures=99), 96),
            ("a_bound_in_the_first_hours", _metric(definition=BOUNDED, exposures=800), 11),
            (
                "a_bound_that_ignores_zeros_under_the_floor",
                _metric(definition={**BOUNDED, "ignore_zeros": True}, exposures=800),
                96,
            ),
            (
                "a_bound_on_the_largest_value",
                _metric(definition={**BOUNDED, "upper_bound_percentile": 1}, exposures=800),
                96,
            ),
            (
                "a_stopped_event_on_a_secondary_metric",
                _metric(role="secondary", definition=BOUNDED, stopped_events={"purchase": LAST_ARRIVED}),
                96,
            ),
            (
                "a_retention_window_that_starts_later",
                _metric(
                    definition={
                        "metric_type": "retention",
                        "retention_window_start": 7,
                        "retention_window_end": 8,
                        "retention_window_unit": "day",
                    }
                ),
                96,
            ),
        ]
    )
    def test_stays_quiet(self, _name: str, metric: ZeroMetric, hours_of_data: float) -> None:
        self.assertIsNone(_outcome(metric, hours_of_data=hours_of_data))

    def test_stays_quiet_when_the_event_never_arrived(self) -> None:
        self.assertIsNone(_outcome(_metric(), events_received={"purchase": False}))

    def test_a_retention_window_that_started_reads_as_zero(self) -> None:
        definition = {
            "metric_type": "retention",
            "retention_window_start": 2,
            "retention_window_end": 3,
            "retention_window_unit": "day",
        }
        self.assertIsInstance(_outcome(_metric(definition=definition)), ExperimentHealthFinding)

    def test_the_outlier_bound_on_a_side_of_a_ratio(self) -> None:
        definition = {"metric_type": "ratio", "denominator_outlier_handling": {"upper_bound_percentile": 0.95}}
        metric = _metric(role="secondary", ratio_side="denominator", definition=definition, exposures=800)

        outcome = _outcome(metric, hours_of_data=18)

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(outcome.subcode, "outlier_bound")
        self.assertIn('The denominator of the secondary metric "Purchases" reads 0', outcome.detail)
        self.assertIn("fewer than 5% have a value", outcome.detail)

    def test_the_outlier_bound_on_the_other_side_of_a_ratio_is_no_cause(self) -> None:
        definition = {"metric_type": "ratio", "denominator_outlier_handling": {"upper_bound_percentile": 0.95}}

        self.assertIsNone(_outcome(_metric(role="secondary", ratio_side="numerator", definition=definition)))

    def test_lists_the_primary_metrics_with_a_cause_first(self) -> None:
        outcome = _outcome(
            _metric(metric_id="a", name="Secondary", role="secondary", definition=BOUNDED),
            _metric(metric_id="b", name="Unexplained"),
            _metric(metric_id="c", name="Bounded", definition=BOUNDED),
        )

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(outcome.title, "3 metrics read zero in every variant")
        self.assertEqual(outcome.subcode, "outlier_bound")
        self.assertEqual(
            [outcome.evidence[f"metric_{number}"] for number in (1, 2, 3)], ["Bounded", "Unexplained", "Secondary"]
        )
        self.assertEqual(outcome.evidence["metric_2_exposures"], 20000)
        self.assertIsNone(outcome.evidence["metric_2_cause"])

    def test_says_the_usual_causes_once(self) -> None:
        outcome = _outcome(
            _metric(metric_id="a", name="Purchases", events=("purchase",)),
            _metric(metric_id="b", name="Refunds", events=("refund",), has_filters=True),
        )

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(outcome.detail.count("same ID as the exposure"), 1)
        self.assertIn("sends the metric events with", outcome.detail)
        self.assertIn("Check that the metric filters match", outcome.detail)
        self.assertLess(outcome.detail.index('"Refunds" reads 0'), outcome.detail.index("same ID as the exposure"))

    @parameterized.expand(
        [
            ("archived", {"archived": True}, "Doesn't run on archived experiments"),
            ("draft", {"is_launched": False}, "Runs after launch"),
        ]
    )
    def test_skips(self, _name: str, changes: dict[str, Any], reason: str) -> None:
        outcome = _outcome(_metric(), **changes)
        assert isinstance(outcome, CheckSkip)
        self.assertEqual(outcome.reason, reason)

    def test_skips_without_a_finished_calculation(self) -> None:
        outcome = _outcome(_metric(), hours_of_data=None)  # type: ignore[arg-type]
        assert isinstance(outcome, CheckSkip)
        self.assertEqual(outcome.reason, "Runs once a calculation of the metrics has finished")


class TestMetricAllZeroFromStoredRuns(BaseTest):
    def _experiment(self, metrics: list[dict[str, Any]], *, started_days_ago: int = 5) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-test",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        return Experiment.objects.create(
            team=self.team,
            name="Checkout",
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=started_days_ago),
            metrics=metrics,
        )

    def _store(self, experiment: Experiment, results: dict[str, dict | None]) -> None:
        with team_scope(self.team.id):
            query_to = timezone.now() - timedelta(hours=1)
            run = ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                status=ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                metric_uuids=list(results),
                query_to=query_to,
            )
            store = MetricResultStore(experiment_id=experiment.id)
            for metric_uuid, result in results.items():
                calculation_config = get_metric_calculation_config(experiment, metric_uuid)
                assert calculation_config is not None and experiment.start_date is not None
                store.record_run_result(
                    str(run.id),
                    calculation_config,
                    window=query_to,
                    query_from=experiment.start_date,
                    result=result or {},
                    query_id=None,
                )
            ExperimentMetricsRecalculation.objects.filter(id=run.id).update(
                status=ExperimentMetricsRecalculation.Status.COMPLETED, completed_at=query_to
            )

    def _findings(self, experiment: Experiment) -> list[ExperimentHealthFinding]:
        health = get_experiment_health(
            team_id=self.team.id, experiment_id=experiment.id, reader_access=NO_QUERIES, user=self.user
        )
        return [finding for finding in health.findings if finding.code == CODE]

    def _mean(self, uuid: str, **changes: Any) -> dict[str, Any]:
        return {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": uuid,
            "name": f"Metric {uuid}",
            "source": {"kind": "EventsNode", "event": "purchase"},
            **changes,
        }

    def _ratio(self, uuid: str) -> dict[str, Any]:
        return {
            "kind": "ExperimentMetric",
            "metric_type": "ratio",
            "uuid": uuid,
            "name": f"Metric {uuid}",
            "numerator": {"kind": "EventsNode", "event": "viewed"},
            "denominator": {"kind": "EventsNode", "event": "added"},
        }

    def _seen(self, event: str, last_seen_at: datetime) -> None:
        EventDefinition.objects.create(team=self.team, project=self.team.project, name=event, last_seen_at=last_seen_at)

    @parameterized.expand(
        [
            ("zero_in_every_variant", _result(samples=1000, total=0), True),
            (
                "a_value_in_one_variant",
                {**_result(samples=1000, total=0), "variant_results": [_variant(samples=1000, total=1)]},
                False,
            ),
            ("values_that_cancel_out", _result(samples=1000, total=0, squares=4), False),
            (
                "a_sum_that_overflowed",
                {
                    **_result(samples=1000, total=0),
                    "baseline": {
                        "key": "control",
                        "number_of_samples": 1000,
                        "sum": None,
                        "sum_squares": None,
                    },
                },
                False,
            ),
        ]
    )
    def test_reads_the_zero_from_the_run_the_page_shows(self, _name: str, result: dict, reports: bool) -> None:
        experiment = self._experiment([self._mean("primary")])
        self._seen("purchase", timezone.now())
        self._store(experiment, {"primary": result})

        self.assertEqual(bool(self._findings(experiment)), reports)

    @parameterized.expand(
        [
            ("numerator", _result(samples=1000, total=0, denominator=20), "The numerator of the primary"),
            ("denominator", _result(samples=1000, total=20, denominator=0), "The denominator of the primary"),
        ]
    )
    def test_reads_the_side_of_a_ratio(self, _name: str, result: dict, words: str) -> None:
        experiment = self._experiment([self._ratio("primary")])
        self._store(experiment, {"primary": result})

        [finding] = self._findings(experiment)

        self.assertIn(words, finding.detail)

    def test_names_only_the_event_of_the_side_that_reads_zero(self) -> None:
        experiment = self._experiment([self._ratio("primary")])
        assert experiment.start_date is not None
        self._seen("viewed", timezone.now())
        self._seen("added", experiment.start_date - timedelta(days=1))
        self._store(experiment, {"primary": _result(samples=1000, total=0, denominator=20)})

        [finding] = self._findings(experiment)

        self.assertIsNone(finding.subcode)
        self.assertIn('the event "viewed"', finding.detail)

    def test_names_an_event_that_stopped_before_launch(self) -> None:
        experiment = self._experiment([self._mean("primary")])
        assert experiment.start_date is not None
        self._seen("purchase", experiment.start_date - timedelta(days=1))
        self._store(experiment, {"primary": _result(samples=1000, total=0)})

        [finding] = self._findings(experiment)

        self.assertEqual(finding.subcode, "event_stopped")

    def test_an_event_that_arrived_after_launch_did_not_stop(self) -> None:
        experiment = self._experiment([self._mean("primary")])
        assert experiment.start_date is not None
        self._seen("purchase", experiment.start_date + timedelta(hours=1))
        self._store(experiment, {"primary": _result(samples=1000, total=0)})

        [finding] = self._findings(experiment)

        self.assertIsNone(finding.subcode)

    def test_measures_the_data_at_the_calculation_that_the_page_shows(self) -> None:
        experiment = self._experiment([self._mean("primary")], started_days_ago=4)
        self._store(experiment, {"primary": _result(samples=1000, total=0)})
        assert experiment.start_date is not None
        with team_scope(self.team.id):
            ExperimentMetricsRecalculation.objects.filter(experiment=experiment).update(
                query_to=experiment.start_date + timedelta(hours=48)
            )

        self.assertEqual(self._findings(experiment), [])

    def test_a_blank_event_name_matches_no_events(self) -> None:
        experiment = self._experiment([self._mean("primary", source={"kind": "EventsNode", "event": ""})])
        self._store(experiment, {"primary": _result(samples=1000, total=0)})

        [finding] = self._findings(experiment)

        self.assertEqual(finding.subcode, "blank_event")
