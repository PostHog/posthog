from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework.exceptions import ValidationError

from posthog.test.persons import create_person

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.replay_context import (
    experiment_prompt_context,
    experiment_status,
    session_variant,
    variant_rollout_shares,
)
from products.experiments.backend.replay_linkage import resolve_exposure_linkage
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FROZEN_NOW = "2026-01-10T20:00:00Z"
BASE_TIME = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)


def _create_experiment(test: BaseTest, *, key: str = "checkout-cta", **kwargs) -> Experiment:
    flag = FeatureFlag.objects.create(
        team=test.team,
        key=key,
        name=key,
        created_by=test.user,
        filters={
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Current checkout", "rollout_percentage": 50},
                    {"key": "test", "name": "One-click checkout", "rollout_percentage": 40},
                    {"key": "beta", "rollout_percentage": 10},
                ]
            }
        },
    )
    defaults: dict = {
        "team": test.team,
        "name": "Checkout CTA copy",
        "feature_flag": flag,
        "created_by": test.user,
        "start_date": BASE_TIME - timedelta(days=8),
        "exposure_criteria": {},
    }
    return Experiment.objects.create(**{**defaults, **kwargs})


# The facade reads Replay Vision builds its experiment scanner on: rollout shares feed
# per-variant sampling, the prompt context feeds the scan prompt, and the status read
# drives the sweep's lifecycle check.
class TestExperimentReplayContext(BaseTest):
    def test_rollout_shares_are_fractions_without_excluded_variants(self) -> None:
        experiment = _create_experiment(self, excluded_variants=["beta"])

        assert variant_rollout_shares(self.team, experiment_id=experiment.pk) == {"control": 0.5, "test": 0.4}

        with self.assertRaises(ValidationError):
            variant_rollout_shares(self.team, experiment_id=experiment.pk + 1)

    def test_prompt_context_describes_the_experiment(self) -> None:
        experiment = _create_experiment(
            self,
            description="One-click checkout raises purchase conversion.",
            excluded_variants=["beta"],
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "name": "Purchases", "source": {}},
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "purchase"},
                },
            ],
        )
        for name, link_type in (("Checkout conversion", "primary"), ("Support tickets", "secondary")):
            saved = ExperimentSavedMetric.objects.create(team=self.team, name=name, query={"kind": "ExperimentMetric"})
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=saved, metadata={"type": link_type}
            )

        context = experiment_prompt_context(self.team, experiment_id=experiment.pk)

        assert context is not None
        assert context.name == "Checkout CTA copy"
        assert context.description == "One-click checkout raises purchase conversion."
        assert context.feature_flag_key == "checkout-cta"
        assert [(v.key, v.description, v.rollout_percentage) for v in context.variants] == [
            ("control", "Current checkout", 50.0),
            ("test", "One-click checkout", 40.0),
        ]
        assert context.primary_metric_names == ("Purchases", "Mean purchase", "Checkout conversion")

        experiment.deleted = True
        experiment.save()
        assert experiment_prompt_context(self.team, experiment_id=experiment.pk) is None

    def test_status_reads_the_lifecycle(self) -> None:
        experiment = _create_experiment(self, running_time_calculation={"recommended_running_time": 14})

        status = experiment_status(self.team, experiment_id=experiment.pk)
        assert status is not None
        assert status.status == "running"
        assert status.planned_duration_days == 14.0
        assert status.is_active

        experiment.end_date = BASE_TIME
        experiment.save()
        ended = experiment_status(self.team, experiment_id=experiment.pk)
        assert ended is not None and not ended.is_active

        experiment.deleted = True
        experiment.save()
        assert experiment_status(self.team, experiment_id=experiment.pk) is None


@time_machine.travel(FROZEN_NOW, tick=False)
class TestSessionVariant(ClickhouseTestMixin, BaseTest):
    def _expose(self, distinct_id: str, variant: str) -> None:
        create_person(team=self.team, distinct_ids=[distinct_id])
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=BASE_TIME,
            properties={"$feature_flag": "checkout-cta", "$feature_flag_response": variant},
        )

    def test_attributes_the_exposed_variant_within_the_requested_set(self) -> None:
        experiment = _create_experiment(self)
        self._expose("control-user", "control")
        self._expose("test-user", "test")
        create_person(team=self.team, distinct_ids=["unexposed-user"])
        flush_persons_and_events()

        all_variants = resolve_exposure_linkage(self.team, experiment_id=experiment.pk)
        assert session_variant(all_variants, "test-user") == "test"
        assert session_variant(all_variants, "control-user") == "control"
        assert session_variant(all_variants, "unexposed-user") is None

        narrowed = resolve_exposure_linkage(self.team, experiment_id=experiment.pk, variants=["test"])
        assert session_variant(narrowed, "control-user") is None
