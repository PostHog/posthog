"""Tests for experiments facade layer."""

from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.experiments.backend.facade import count_running_experiments_on_feature_flag_called, create_experiment
from products.experiments.backend.facade.contracts import CreateExperimentInput
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

PAGEVIEW_EXPOSURE = {
    "exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "$pageview", "properties": []}
}


class TestCreateExperiment(APIBaseTest):
    """Tests for create_experiment facade function."""

    def test_create_experiment_minimal_fields(self):
        """Test creating experiment with only required fields."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify DTO fields
        assert result.name == "Test Experiment"
        assert result.feature_flag_key == "test-flag"
        assert result.is_draft is True
        assert result.description is None or result.description == ""

        # Verify model was created
        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.name == "Test Experiment"
        assert experiment.feature_flag.key == "test-flag"
        assert experiment.feature_flag_rule_id is None
        assert experiment.feature_flag_rule_snapshot is None

    def test_create_experiment_with_description(self):
        """Test creating experiment with description."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-2",
            description="Testing the facade layer",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.description == "Testing the facade layer"

    def test_create_experiment_with_experiment_own_parameters(self):
        """parameters carries experiment-own keys (variant_notes) and is persisted verbatim."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-3",
            parameters={"variant_notes": {"control": "baseline", "test": "new checkout"}},
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.parameters == {"variant_notes": {"control": "baseline", "test": "new checkout"}}

    @time_machine.travel("2025-01-01 12:00:00", tick=False)
    def test_create_experiment_with_start_date(self):
        """Test creating launched (non-draft) experiment."""
        start_date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-6",
            start_date=start_date,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.is_draft is False
        assert result.start_date == start_date

    def test_create_experiment_with_metrics(self):
        """Test creating experiment with metrics."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-7",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
            allow_unknown_events=True,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify experiment was created with metrics
        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1

    def test_create_experiment_with_all_fields(self):
        """Test creating experiment with comprehensive field set."""
        input_dto = CreateExperimentInput(
            name="Comprehensive Test",
            feature_flag_key="test-flag-8",
            description="Full feature test",
            type="web",
            parameters={"minimum_detectable_effect": 5},
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
            stats_config={"method": "bayesian"},
            exposure_criteria={"filter_test_accounts": True},
            archived=False,
            deleted=False,
            allow_unknown_events=True,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.name == "Comprehensive Test"
        assert result.description == "Full feature test"


class TestCountRunningExperimentsOnFeatureFlagCalled(BaseTest):
    @parameterized.expand(
        [
            ("running_on_the_default_exposure", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, False, False, 1),
            (
                "custom_exposure_event",
                PAGEVIEW_EXPOSURE,
                datetime(2026, 8, 1, tzinfo=UTC),
                None,
                False,
                False,
                False,
                0,
            ),
            ("draft", {}, None, None, False, False, False, 0),
            ("ended", {}, datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 20, tzinfo=UTC), False, False, False, 0),
            ("archived", {}, datetime(2026, 8, 1, tzinfo=UTC), None, True, False, False, 0),
            ("deleted", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, True, False, 0),
            ("another_organization", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, False, True, 0),
        ]
    )
    def test_counts_only_running_experiments_that_count_exposures_on_feature_flag_called(
        self,
        _name: str,
        exposure_criteria: dict,
        start_date: datetime | None,
        end_date: datetime | None,
        archived: bool,
        deleted: bool,
        other_organization: bool,
        expected: int,
    ) -> None:
        team = (
            Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
            if other_organization
            else self.team
        )
        flag = FeatureFlag.objects.create(team=team, key="experiment-flag", created_by=self.user)
        Experiment.objects.create(
            team=team,
            name="Experiment",
            feature_flag=flag,
            exposure_criteria=exposure_criteria,
            start_date=start_date,
            end_date=end_date,
            archived=archived,
            deleted=deleted,
        )

        assert count_running_experiments_on_feature_flag_called(self.organization.id) == expected
