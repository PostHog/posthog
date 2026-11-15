from datetime import timedelta
from typing import Any, cast

import time_machine
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    EventsNode,
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
)

from products.experiments.backend.facade.enums import PrecomputeSkipReason
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from products.experiments.backend.models.experiment import Experiment, build_rule_snapshot
from products.feature_flags.backend.models.feature_flag import FeatureFlag

LINKED_RULE = "11111111-1111-4111-8111-111111111111"
OTHER_RULE = "22222222-2222-4222-8222-222222222222"


def _experiment_rule(rule_id: str, *, weights: tuple[int, int] = (50, 50)) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "experiment",
        "targeting": {"properties": []},
        "paused": False,
        "rollout_percentage": 100,
        "on_rollout_miss": "continue",
        "assignment_algorithm": "sha1_60_v1",
        "seed": f"seed-{rule_id}",
        # Both variants return the same value, so only the variant key tells the arms apart.
        "variants": [
            {"key": "control", "weight": weights[0], "value": True},
            {"key": "test", "weight": weights[1], "value": True},
        ],
    }


@override_settings(IN_UNIT_TESTING=True)
class TestRuleLinkedExperiment(ExperimentQueryRunnerBaseTest):
    def _create_rule_linked_experiment(self, *, start_date=None, weights: tuple[int, int] = (50, 50)) -> Experiment:
        self.flag = FeatureFlag.objects.create(
            name="Flag with rules",
            key="flag-with-rules",
            team=self.team,
            created_by=self.user,
            filters={
                "version": 2,
                "return_type": "boolean",
                "default_value": False,
                "rules": [_experiment_rule(LINKED_RULE, weights=weights), _experiment_rule(OTHER_RULE)],
            },
        )
        return Experiment.objects.create(
            name="rule-linked",
            team=self.team,
            feature_flag=self.flag,
            feature_flag_rule_id=LINKED_RULE,
            feature_flag_rule_snapshot=build_rule_snapshot(self.flag, LINKED_RULE),
            start_date=start_date or timezone.now(),
            end_date=timezone.now() + timedelta(days=14),
            exposure_criteria=None,
        )

    def _event(self, distinct_id: str, event: str, properties: dict[str, Any], minute: int = 0) -> None:
        _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            timestamp=f"2020-01-02T12:{minute:02d}:00Z",
            properties=properties,
        )

    def _expose(
        self,
        distinct_id: str,
        variant_key: str,
        *,
        rule_id: str | None = LINKED_RULE,
        event: str = "$experiment_exposure",
        minute: int = 0,
        other_properties: dict[str, Any] | None = None,
    ) -> None:
        properties: dict[str, Any] = {
            "$feature_flag": self.flag.key,
            "$feature_flag_response": True,
            "$feature_flag_variant_key": variant_key,
            "locally_evaluated": False,
        }
        if rule_id is not None:
            properties["$feature_flag_rule_id"] = rule_id
        self._event(distinct_id, event, {**properties, **(other_properties or {})}, minute=minute)

    def _purchase(self, distinct_id: str, amount: int = 10) -> None:
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=distinct_id,
            timestamp="2020-01-02T12:30:00Z",
            properties={"amount": amount},
        )

    def _mean_query(self, experiment: Experiment) -> ExperimentQuery:
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount")
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()
        return ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)

    def _samples_and_sums(self, result: ExperimentQueryResponse) -> dict[str, tuple[int, float]]:
        assert result.baseline is not None and result.variant_results is not None
        return {row.key: (row.number_of_samples, row.sum) for row in [result.baseline, *result.variant_results]}

    @time_machine.travel("2020-01-01T12:00:00Z", tick=False)
    def test_counts_only_the_sdk_exposures_of_the_linked_rule_by_variant_key(self):
        experiment = self._create_rule_linked_experiment()
        query = self._mean_query(experiment)

        for index in range(3):
            self._expose(f"control_{index}", "control")
            self._purchase(f"control_{index}", amount=10)
        for index in range(4):
            self._expose(f"test_{index}", "test")
            self._purchase(f"test_{index}", amount=20)

        self._expose("other_rule", "test", rule_id=OTHER_RULE)
        self._expose(
            "flag_call_only",
            "test",
            event="$feature_flag_called",
            other_properties={"$feature_flag_config_version": 2},
        )
        self._expose("copy_without_rule", "test", rule_id=None, other_properties={"$feature_flag_response": "test"})
        self._expose("unknown_variant", "holdout")
        self._expose("other_flag", "test", other_properties={"$feature_flag": "another-flag"})
        for distinct_id in ("other_rule", "flag_call_only", "copy_without_rule", "unknown_variant", "other_flag"):
            self._purchase(distinct_id, amount=1000)
        flush_persons_and_events()

        runner = ExperimentQueryRunner(query=query, team=self.team)
        result = cast(ExperimentQueryResponse, runner.calculate())

        assert self._samples_and_sums(result) == {"control": (3, 30), "test": (4, 80)}

    @time_machine.travel("2020-01-01T12:00:00Z", tick=False)
    def test_an_entity_exposed_to_two_variants_of_the_rule_is_left_out(self):
        experiment = self._create_rule_linked_experiment()
        query = self._mean_query(experiment)
        self._expose("control_only", "control")
        self._expose("test_only", "test")
        self._expose("both", "control")
        self._expose("both", "test", minute=5)
        self._purchase("both", amount=1000)
        flush_persons_and_events()

        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

        assert self._samples_and_sums(result) == {"control": (1, 0), "test": (1, 0)}

    @time_machine.travel("2020-01-01T12:00:00Z", tick=False)
    def test_funnel_metric_starts_at_the_exposure_of_the_rule(self):
        experiment = self._create_rule_linked_experiment()
        metric = ExperimentFunnelMetric(series=[EventsNode(event="purchase")])
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()
        for index in range(4):
            self._expose(f"control_{index}", "control")
            self._expose(f"test_{index}", "test")
        self._expose("other_rule", "test", rule_id=OTHER_RULE)
        for distinct_id in ("control_0", "test_0", "test_1", "test_2", "other_rule"):
            self._purchase(distinct_id)
        flush_persons_and_events()

        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

        assert self._samples_and_sums(result) == {"control": (4, 1), "test": (4, 3)}

    @parameterized.expand(
        [
            ("rule_removed", {"version": 2, "return_type": "boolean", "default_value": False, "rules": []}),
            (
                "rule_replaced_by_a_release",
                {
                    "version": 2,
                    "return_type": "boolean",
                    "default_value": False,
                    "rules": [
                        {
                            "id": LINKED_RULE,
                            "rule_type": "targeted_release",
                            "targeting": {"properties": []},
                            "value": True,
                        }
                    ],
                },
            ),
        ]
    )
    @time_machine.travel("2020-01-01T12:00:00Z", tick=False)
    def test_results_read_the_snapshot_after_the_flag_changes(self, _name: str, later_filters: dict[str, Any]):
        experiment = self._create_rule_linked_experiment()
        query = self._mean_query(experiment)
        self._expose("control_0", "control")
        self._expose("test_0", "test")
        self._purchase("test_0", amount=20)
        flush_persons_and_events()
        self.flag.filters = later_filters
        self.flag.save()

        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())

        assert self._samples_and_sums(result) == {"control": (1, 0), "test": (1, 20)}

    @time_machine.travel("2020-01-03T12:00:00Z", tick=False)
    def test_a_flag_renamed_after_the_launch_keeps_its_exposures(self):
        experiment = self._create_rule_linked_experiment(start_date=timezone.now() - timedelta(days=2))
        query = self._mean_query(experiment)
        self._expose("control_0", "control")
        self._expose("test_0", "test")
        self._purchase("test_0", amount=20)
        flush_persons_and_events()
        self.flag.key = "renamed-flag"
        self.flag.save()

        result = cast(ExperimentQueryResponse, ExperimentQueryRunner(query=query, team=self.team).calculate())
        exposures = cast(
            ExperimentExposureQueryResponse,
            ExperimentExposuresQueryRunner(query=self._exposure_query(experiment), team=self.team).calculate(),
        )

        assert self._samples_and_sums(result) == {"control": (1, 0), "test": (1, 20)}
        assert exposures.total_exposures == {"control": 1, "test": 1}

    @time_machine.travel("2020-01-07T12:00:00Z", tick=False)
    def test_never_reads_precomputed_exposures(self):
        # Old enough for the minimum runtime, on a team with precomputation on: every other gate is open.
        experiment = self._create_rule_linked_experiment(start_date=timezone.now() - timedelta(days=5))
        self._enable_precomputation()
        query = self._mean_query(experiment)

        runner = ExperimentQueryRunner(query=query, team=self.team)
        result = cast(ExperimentQueryResponse, runner.calculate())

        assert not runner._exposures_precompute_applicable()
        assert runner._precompute_skip_reason() == PrecomputeSkipReason.FLAG_RULE
        assert result.is_precomputed is False

    @time_machine.travel("2020-01-03T12:00:00Z", tick=False)
    def test_exposures_runner_counts_the_rule_and_reads_the_split_from_its_weights(self):
        experiment = self._create_rule_linked_experiment(
            start_date=timezone.now() - timedelta(days=2), weights=(30, 70)
        )
        for index in range(2):
            self._expose(f"control_{index}", "control")
        for index in range(5):
            self._expose(f"test_{index}", "test")
        self._expose("other_rule", "test", rule_id=OTHER_RULE)
        self._expose("flag_call_only", "test", event="$feature_flag_called")
        flush_persons_and_events()

        runner = ExperimentExposuresQueryRunner(query=self._exposure_query(experiment), team=self.team)
        response = cast(ExperimentExposureQueryResponse, runner.calculate())

        assert response.total_exposures == {"control": 2, "test": 5}
        assert [series.variant for series in response.timeseries] == ["control", "test"]
        assert runner._multivariate_data() == {
            "variants": [{"key": "control", "rollout_percentage": 30}, {"key": "test", "rollout_percentage": 70}]
        }
        assert response.health_checks == []
        assert response.health_findings == []

    @parameterized.expand(
        [
            ("snapshot_missing", {"feature_flag_rule_snapshot": None}, "rule can't be read"),
            ("snapshot_of_another_rule", {"feature_flag_rule_id": OTHER_RULE}, "rule can't be read"),
            (
                "custom_exposure_event",
                {
                    "exposure_criteria": {
                        "exposure_config": {
                            "kind": "ExperimentEventExposureConfig",
                            "event": "$pageview",
                            "properties": [],
                        }
                    }
                },
                "custom exposure event",
            ),
        ]
    )
    @time_machine.travel("2020-01-01T12:00:00Z", tick=False)
    def test_a_query_fails_instead_of_falling_back(self, _name: str, stored: dict[str, Any], message: str):
        experiment = self._create_rule_linked_experiment()
        query = self._mean_query(experiment)
        # Written past the model, which refuses to save a started experiment without its snapshot.
        Experiment.objects.filter(pk=experiment.pk).update(**stored)
        experiment.refresh_from_db()

        with self.assertRaisesMessage(ValidationError, message):
            ExperimentQueryRunner(query=query, team=self.team)
        with self.assertRaisesMessage(ValidationError, message):
            ExperimentExposuresQueryRunner(query=self._exposure_query(experiment), team=self.team)

    def _exposure_query(self, experiment: Experiment) -> ExperimentExposureQuery:
        return ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag={"key": self.flag.key, "filters": self.flag.filters},
            start_date=experiment.start_date.isoformat() if experiment.start_date else None,
            end_date=None,
            exposure_criteria=experiment.exposure_criteria,
        )
