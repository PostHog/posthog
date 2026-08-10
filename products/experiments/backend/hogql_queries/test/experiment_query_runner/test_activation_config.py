from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.forms.models import model_to_dict
from django.test import override_settings

from posthog.schema import (
    EventsNode,
    ExperimentExposureQuery,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
)

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

ACTIVATION_CRITERIA = {
    "activation_config": {
        "kind": "ExperimentEventExposureConfig",
        "event": "activated",
        "properties": [],
    }
}


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentActivationConfig(ExperimentQueryRunnerBaseTest):
    snapshot_replace_all_numbers = True

    def _create_flag_exposure(self, distinct_id, feature_flag, variant, timestamp):
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$feature_flag_response": variant,
                "$feature_flag": feature_flag.key,
            },
        )

    # Activation and metric events deliberately carry no $feature/<key> property:
    # activation mode must work without flag properties stamped on other events.
    def _create_plain_event(self, distinct_id, event, timestamp):
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={},
        )

    def _create_activation_experiment(self, feature_flag):
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 10),
        )
        experiment.stats_config = {"method": "frequentist"}
        experiment.exposure_criteria = ACTIVATION_CRITERIA
        return experiment

    def _seed_mean_scenario(self, feature_flag):
        for variant, extra_purchases in (("control", 0), ("test", 1)):
            for i in range(3):
                user = f"user_{variant}_{i}"
                _create_person(distinct_ids=[user], team_id=self.team.pk)
                self._create_flag_exposure(user, feature_flag, variant, "2020-01-02T12:00:00Z")
                # Purchase between flag exposure and activation must not count
                self._create_plain_event(user, "purchase", "2020-01-02T12:10:00Z")
                self._create_plain_event(user, "activated", "2020-01-02T12:30:00Z")
                self._create_plain_event(user, "purchase", "2020-01-02T12:40:00Z")
                for j in range(extra_purchases):
                    self._create_plain_event(user, "purchase", f"2020-01-02T12:5{j}:00Z")

        # Flag exposure but never activated: not part of the analysis
        _create_person(distinct_ids=["user_flag_only"], team_id=self.team.pk)
        self._create_flag_exposure("user_flag_only", feature_flag, "control", "2020-01-02T12:00:00Z")
        self._create_plain_event("user_flag_only", "purchase", "2020-01-02T12:10:00Z")

        # Activated only before the flag exposure: ordering not satisfied
        _create_person(distinct_ids=["user_pre_activation"], team_id=self.team.pk)
        self._create_plain_event("user_pre_activation", "activated", "2020-01-02T11:00:00Z")
        self._create_flag_exposure("user_pre_activation", feature_flag, "control", "2020-01-02T12:00:00Z")
        self._create_plain_event("user_pre_activation", "purchase", "2020-01-02T12:10:00Z")

        # Saw both variants: excluded by default multiple-variant handling
        _create_person(distinct_ids=["user_multi_variant"], team_id=self.team.pk)
        self._create_flag_exposure("user_multi_variant", feature_flag, "control", "2020-01-02T12:00:00Z")
        self._create_flag_exposure("user_multi_variant", feature_flag, "test", "2020-01-02T12:05:00Z")
        self._create_plain_event("user_multi_variant", "activated", "2020-01-02T12:30:00Z")
        self._create_plain_event("user_multi_variant", "purchase", "2020-01-02T12:40:00Z")

        flush_persons_and_events()

    def _assert_mean_scenario_results(self, experiment, metric):
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(test_variant.sum, 6)

    @freeze_time("2020-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_anchors_exposure_on_activation_event(self):
        feature_flag = self.create_feature_flag()
        experiment = self._create_activation_experiment(feature_flag)

        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self._seed_mean_scenario(feature_flag)
        self._assert_mean_scenario_results(experiment, metric)

    @freeze_time("2020-01-10T12:00:00Z")
    def test_team_precomputation_does_not_change_activation_results(self):
        self._setup_precomputation_test(True)

        feature_flag = self.create_feature_flag()
        experiment = self._create_activation_experiment(feature_flag)

        metric = ExperimentMeanMetric(source=EventsNode(event="purchase"))
        experiment.metrics = [metric.model_dump(mode="json")]
        self._save_experiment_with_precomputation(experiment, True)

        self._seed_mean_scenario(feature_flag)
        # The per-day exposure cache is built from the flag predicate alone: reading it would
        # pull flag-only and pre-activation users into the denominator and anchor metrics on
        # the flag time. Activation mode must produce identical results with precompute on.
        self._assert_mean_scenario_results(experiment, metric)
        self.assertEqual(PreaggregationJob.objects.count(), 0)

    @freeze_time("2020-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_counts_conversions_after_activation_only(self):
        feature_flag = self.create_feature_flag()
        experiment = self._create_activation_experiment(feature_flag)

        metric = ExperimentFunnelMetric(series=[EventsNode(event="purchase")])
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant in ("control", "test"):
            # Converts: flag -> activated -> purchase
            converter = f"user_{variant}_converts"
            _create_person(distinct_ids=[converter], team_id=self.team.pk)
            self._create_flag_exposure(converter, feature_flag, variant, "2020-01-02T12:00:00Z")
            self._create_plain_event(converter, "activated", "2020-01-02T12:30:00Z")
            self._create_plain_event(converter, "purchase", "2020-01-02T12:40:00Z")

            # Exposed, but purchased before activating: no conversion
            early_buyer = f"user_{variant}_early"
            _create_person(distinct_ids=[early_buyer], team_id=self.team.pk)
            self._create_flag_exposure(early_buyer, feature_flag, variant, "2020-01-02T12:00:00Z")
            self._create_plain_event(early_buyer, "purchase", "2020-01-02T12:10:00Z")
            self._create_plain_event(early_buyer, "activated", "2020-01-02T12:30:00Z")

        flush_persons_and_events()

        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

        assert result.baseline is not None
        assert result.variant_results is not None

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 2)
        self.assertEqual(control_variant.sum, 1)  # success_count
        self.assertEqual(test_variant.sum, 1)  # success_count

    @freeze_time("2020-01-10T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposures_timeseries_counts_users_on_activation_day(self):
        feature_flag = self.create_feature_flag()
        experiment = self._create_activation_experiment(feature_flag)
        experiment.save()

        # Control: flag on Jan 2, activated on Jan 4 -> exposed on Jan 4
        _create_person(distinct_ids=["user_control"], team_id=self.team.pk)
        self._create_flag_exposure("user_control", feature_flag, "control", "2020-01-02T12:00:00Z")
        self._create_plain_event("user_control", "activated", "2020-01-04T12:00:00Z")

        # Control: flag only, never activated -> not exposed
        _create_person(distinct_ids=["user_control_flag_only"], team_id=self.team.pk)
        self._create_flag_exposure("user_control_flag_only", feature_flag, "control", "2020-01-02T12:00:00Z")

        # Test: flag and activation on Jan 2 -> exposed on Jan 2
        _create_person(distinct_ids=["user_test"], team_id=self.team.pk)
        self._create_flag_exposure("user_test", feature_flag, "test", "2020-01-02T12:00:00Z")
        self._create_plain_event("user_test", "activated", "2020-01-02T13:00:00Z")

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag=model_to_dict(feature_flag),
            holdout=None,
            start_date=experiment.start_date.isoformat() if experiment.start_date else None,
            end_date=experiment.end_date.isoformat() if experiment.end_date else None,
            exposure_criteria=experiment.exposure_criteria,
        )
        response = ExperimentExposuresQueryRunner(team=self.team, query=query).calculate()

        self.assertEqual(response.total_exposures, {"control": 1, "test": 1})

        control_series = next(series for series in response.timeseries if series.variant == "control")
        test_series = next(series for series in response.timeseries if series.variant == "test")

        # Cumulative counts flip to 1 on the activation day, not the flag day
        control_first_exposed_day = control_series.days[control_series.exposure_counts.index(1)]
        test_first_exposed_day = test_series.days[test_series.exposure_counts.index(1)]
        self.assertEqual(control_first_exposed_day, "2020-01-04")
        self.assertEqual(test_first_exposed_day, "2020-01-02")
