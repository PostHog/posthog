"""Tests for experiments facade layer."""

from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from products.experiments.backend.facade import create_experiment
from products.experiments.backend.facade.contracts import CreateExperimentInput


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

    def test_create_experiment_with_description(self):
        """Test creating experiment with description."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-2",
            description="Testing the facade layer",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.description == "Testing the facade layer"

    def test_create_experiment_with_parameters_old_format(self):
        """Test creating experiment with old format (parameters.feature_flag_variants)."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-3",
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.name == "Test Experiment"

        # Verify feature flag has correct variants
        from posthog.models.feature_flag import FeatureFlag

        flag = FeatureFlag.objects.get(id=result.feature_flag_id)
        assert len(flag.variants) == 2

    @freeze_time("2025-01-01 12:00:00")
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
