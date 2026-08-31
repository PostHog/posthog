"""Tests for experiments facade layer."""

from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from products.experiments.backend.facade import create_experiment, get_pulse_experiment_lifecycle
from products.experiments.backend.facade.contracts import CreateExperimentInput
from products.experiments.backend.models.experiment import (
    Experiment as ExperimentModel,
    ExperimentMetricResult,
)


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

    def test_pulse_lifecycle_keeps_an_inert_draft_pending(self):
        """A Pulse draft must not become adopted before a person launches it."""
        experiment = create_experiment(
            team=self.team,
            user=self.user,
            input_dto=CreateExperimentInput(name="Draft checkout", feature_flag_key="pulse-draft-checkout"),
        )

        lifecycle = get_pulse_experiment_lifecycle(team_id=self.team.id, experiment_id=experiment.id)

        assert lifecycle is not None
        assert lifecycle.state == "draft"
        assert lifecycle.launched_at is None
        assert lifecycle.result_state == "not_ready"
        assert lifecycle.observed_value is None

    def test_pulse_lifecycle_uses_the_experiment_launch_time(self):
        """The outcome schedule must be anchored to the authoritative start_date."""
        start_date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        experiment = create_experiment(
            team=self.team,
            user=self.user,
            input_dto=CreateExperimentInput(
                name="Launched checkout", feature_flag_key="pulse-launched-checkout", start_date=start_date
            ),
        )

        lifecycle = get_pulse_experiment_lifecycle(team_id=self.team.id, experiment_id=experiment.id)

        assert lifecycle is not None
        assert lifecycle.state == "launched"
        assert lifecycle.launched_at == start_date
        assert lifecycle.result_state == "not_ready"

    def test_pulse_lifecycle_reports_deleted_drafts_without_a_result(self):
        """A deleted draft is abandonment, not a measured or launched experiment."""
        experiment = create_experiment(
            team=self.team,
            user=self.user,
            input_dto=CreateExperimentInput(
                name="Deleted checkout", feature_flag_key="pulse-deleted-checkout", deleted=True
            ),
        )

        lifecycle = get_pulse_experiment_lifecycle(team_id=self.team.id, experiment_id=experiment.id)

        assert lifecycle is not None
        assert lifecycle.state == "deleted"
        assert lifecycle.launched_at is None
        assert lifecycle.result_state == "not_ready"

    def test_pulse_lifecycle_keeps_completed_untyped_results_retryable(self):
        metric_uuid = "pulse-primary-metric"
        start_date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        created = create_experiment(
            team=self.team,
            user=self.user,
            input_dto=CreateExperimentInput(
                name="Completed checkout result",
                feature_flag_key="pulse-completed-checkout",
                start_date=start_date,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "uuid": metric_uuid,
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
                metrics_ordering=(metric_uuid,),
                allow_unknown_events=True,
            ),
        )
        experiment = ExperimentModel.objects.get(id=created.id)
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid=metric_uuid,
            query_from=start_date,
            query_to=start_date,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"variants": [{"value": "not-an-authoritative-scalar"}]},
            completed_at=start_date,
        )

        lifecycle = get_pulse_experiment_lifecycle(team_id=self.team.id, experiment_id=experiment.id)

        assert lifecycle is not None
        assert lifecycle.result_state == "not_ready"
        assert lifecycle.observed_value is None
        assert lifecycle.delta is None
        assert lifecycle.confidence is None
        assert lifecycle.verdict is None

    def test_pulse_lifecycle_requires_the_exact_team(self):
        experiment = create_experiment(
            team=self.team,
            user=self.user,
            input_dto=CreateExperimentInput(name="Team-bound draft", feature_flag_key="pulse-team-bound"),
        )

        assert get_pulse_experiment_lifecycle(team_id=self.team.id + 1, experiment_id=experiment.id) is None

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
