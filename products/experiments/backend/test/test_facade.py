"""Tests for experiments facade layer."""

from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from products.experiments.backend.facade import create_experiment
from products.experiments.backend.facade.contracts import CreateExperimentInput


# Saved metrics imports (Task 1)
def test_saved_metric_imports():
    """Verify saved metric DTOs can be imported."""
    from products.experiments.backend.facade.saved_metric_contracts import (
        CreateSavedMetricInput,
        ExperimentSavedMetric,
        UpdateSavedMetricInput,
    )

    assert CreateSavedMetricInput is not None
    assert UpdateSavedMetricInput is not None
    assert ExperimentSavedMetric is not None


# Facade exports test (Task 5)
def test_facade_exports():
    """Verify facade functions are exported from __init__."""
    from products.experiments.backend.facade import (
        CreateSavedMetricInput,
        ExperimentSavedMetric,
        ListSavedMetricsInput,
        UpdateSavedMetricInput,
        create_saved_metric,
        delete_saved_metric,
        get_saved_metric,
        list_saved_metrics,
        update_saved_metric,
    )

    assert create_saved_metric is not None
    assert update_saved_metric is not None
    assert delete_saved_metric is not None
    assert list_saved_metrics is not None
    assert get_saved_metric is not None
    assert CreateSavedMetricInput is not None
    assert UpdateSavedMetricInput is not None
    assert ExperimentSavedMetric is not None
    assert ListSavedMetricsInput is not None


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


class TestCreateSavedMetric(APIBaseTest):
    """Tests for create_saved_metric facade function."""

    def test_create_saved_metric_minimal_fields(self):
        """Test creating saved metric with only required fields."""
        from products.experiments.backend.facade.saved_metric_api import create_saved_metric
        from products.experiments.backend.facade.saved_metric_contracts import CreateSavedMetricInput

        input_dto = CreateSavedMetricInput(
            name="Test Metric",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )

        result = create_saved_metric(team=self.team, user=self.user, input_dto=input_dto)

        assert result.name == "Test Metric"
        assert result.query["kind"] == "ExperimentMetric"
        assert result.query["metric_type"] == "mean"
        assert result.description is None

        # Verify model was created
        from products.experiments.backend.models.experiment import ExperimentSavedMetric

        metric = ExperimentSavedMetric.objects.get(id=result.id)
        assert metric.name == "Test Metric"
        assert metric.team_id == self.team.id


class TestUpdateSavedMetric(APIBaseTest):
    """Tests for update_saved_metric facade function."""

    def test_update_saved_metric(self):
        """Test updating a saved metric."""
        from products.experiments.backend.facade.saved_metric_api import create_saved_metric, update_saved_metric
        from products.experiments.backend.facade.saved_metric_contracts import (
            CreateSavedMetricInput,
            UpdateSavedMetricInput,
        )

        # Create a saved metric first
        create_input = CreateSavedMetricInput(
            name="Original Name",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        created = create_saved_metric(team=self.team, user=self.user, input_dto=create_input)

        # Update it
        update_input = UpdateSavedMetricInput(
            name="Updated Name",
            description="New description",
        )
        result = update_saved_metric(
            team=self.team,
            user=self.user,
            saved_metric_id=created.id,
            input_dto=update_input,
        )

        assert result.name == "Updated Name"
        assert result.description == "New description"
        assert result.id == created.id


class TestDeleteSavedMetric(APIBaseTest):
    """Tests for delete_saved_metric facade function."""

    def test_delete_saved_metric(self):
        """Test deleting a saved metric."""
        from products.experiments.backend.facade.saved_metric_api import create_saved_metric, delete_saved_metric
        from products.experiments.backend.facade.saved_metric_contracts import CreateSavedMetricInput

        # Create a saved metric first
        create_input = CreateSavedMetricInput(
            name="To Delete",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        created = create_saved_metric(team=self.team, user=self.user, input_dto=create_input)

        # Delete it
        delete_saved_metric(team=self.team, user=self.user, saved_metric=created)

        # Verify it's deleted
        from products.experiments.backend.models.experiment import ExperimentSavedMetric

        assert not ExperimentSavedMetric.objects.filter(id=created.id).exists()


class TestListSavedMetrics(APIBaseTest):
    """Tests for list_saved_metrics facade function."""

    def test_list_saved_metrics_empty(self):
        """Test listing when no saved metrics exist."""
        from products.experiments.backend.facade.saved_metric_api import list_saved_metrics
        from products.experiments.backend.facade.saved_metric_contracts import ListSavedMetricsInput

        input_dto = ListSavedMetricsInput()
        result = list_saved_metrics(team=self.team, user=self.user, input_dto=input_dto)

        assert result == []

    def test_list_saved_metrics_with_data(self):
        """Test listing saved metrics."""
        from products.experiments.backend.facade.saved_metric_api import create_saved_metric, list_saved_metrics
        from products.experiments.backend.facade.saved_metric_contracts import (
            CreateSavedMetricInput,
            ListSavedMetricsInput,
        )

        # Create two saved metrics
        create_saved_metric(
            team=self.team,
            user=self.user,
            input_dto=CreateSavedMetricInput(
                name="Metric A",
                query={
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ),
        )
        create_saved_metric(
            team=self.team,
            user=self.user,
            input_dto=CreateSavedMetricInput(
                name="Metric B",
                query={
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
                },
            ),
        )

        input_dto = ListSavedMetricsInput()
        result = list_saved_metrics(team=self.team, user=self.user, input_dto=input_dto)

        assert len(result) == 2
        # Should be ordered by name (case-insensitive)
        assert result[0].name == "Metric A"
        assert result[1].name == "Metric B"


class TestGetSavedMetric(APIBaseTest):
    """Tests for get_saved_metric facade function."""

    def test_get_saved_metric(self):
        """Test retrieving a single saved metric."""
        from products.experiments.backend.facade.saved_metric_api import create_saved_metric, get_saved_metric
        from products.experiments.backend.facade.saved_metric_contracts import CreateSavedMetricInput

        created = create_saved_metric(
            team=self.team,
            user=self.user,
            input_dto=CreateSavedMetricInput(
                name="Test Metric",
                query={
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                description="Test description",
            ),
        )

        result = get_saved_metric(team=self.team, user=self.user, saved_metric_id=created.id)

        assert result.id == created.id
        assert result.name == "Test Metric"
        assert result.description == "Test description"
