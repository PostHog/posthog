from posthog.test.base import BaseTest

from products.experiments.backend.presentation.serializers import ExperimentMetricsRecalculationSerializer


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
