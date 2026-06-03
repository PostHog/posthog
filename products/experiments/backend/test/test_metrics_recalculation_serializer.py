from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.presentation.serializers import ExperimentMetricsRecalculationSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentMetricsRecalculationSerializer(BaseTest):
    def test_serializes_status_payload(self):
        payload = {
            "id": "00000000-0000-0000-0000-000000000001",
            "experiment_id": 7,
            "status": "in_progress",
            "total_metrics": 3,
            "completed_metrics": 1,
            "failed_metrics": 0,
            "metric_errors": {"m1": {"step": "calculation", "message": "boom"}},
            "trigger": "manual",
            "created_at": "2026-05-28T10:00:00Z",
            "started_at": "2026-05-28T10:00:01Z",
            "completed_at": None,
        }
        data = ExperimentMetricsRecalculationSerializer(payload).data
        assert data["status"] == "in_progress"
        assert data["total_metrics"] == 3
        assert data["completed_metrics"] == 1
        assert data["failed_metrics"] == 0
        assert data["experiment_id"] == 7
        assert data["trigger"] == "manual"
        assert data["completed_at"] is None
        # Field is metric_errors (not errors) to avoid shadowing DRF's Serializer.errors property.
        assert data["metric_errors"] == {"m1": {"step": "calculation", "message": "boom"}}
        assert "errors" not in data

    def test_serializes_model_instance(self):
        # Read off a real model instance, not a dict. Locks in that metric_errors round-trips through DRF
        # — the bug to avoid is the model attribute being named one thing and the serializer field another,
        # which silently yields None when DRF reads instance.metric_errors and finds nothing.
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="serializer-instance-flag",
            name="flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        experiment = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag, name="exp")
        with team_scope(self.team.id, canonical=True):
            recalc = ExperimentMetricsRecalculation.objects.create(
                team=self.team,
                experiment=experiment,
                metric_errors={"m1": {"step": "calculation", "message": "boom"}},
            )
        data = ExperimentMetricsRecalculationSerializer(recalc).data
        assert data["metric_errors"] == {"m1": {"step": "calculation", "message": "boom"}}
        assert "errors" not in data
