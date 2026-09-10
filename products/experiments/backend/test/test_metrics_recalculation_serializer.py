from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.presentation.serializers import (
    ExperimentMetricsRecalculationSerializer,
    MetricRecalculationResultSerializer,
    RecalculateMetricsRequestSerializer,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentMetricsRecalculationSerializer(BaseTest):
    def test_serializes_status_payload(self):
        payload = {
            "id": "00000000-0000-0000-0000-000000000001",
            "experiment_id": 7,
            "status": "in_progress",
            "total_metrics": 3,
            "metric_errors": {"m1": {"step": "calculation", "message": "boom"}},
            "trigger": "manual",
            "created_at": "2026-05-28T10:00:00Z",
            "started_at": "2026-05-28T10:00:01Z",
            "completed_at": None,
            "query_to": "2026-05-28T10:00:01Z",
        }
        data = ExperimentMetricsRecalculationSerializer(payload).data
        assert data["status"] == "in_progress"
        assert data["total_metrics"] == 3
        assert data["experiment_id"] == 7
        assert data["trigger"] == "manual"
        assert data["completed_at"] is None
        assert data["query_to"] == "2026-05-28T10:00:01Z"
        # Field is metric_errors (not errors) to avoid shadowing DRF's Serializer.errors property.
        assert data["metric_errors"] == {"m1": {"step": "calculation", "message": "boom"}}
        assert "errors" not in data
        assert "completed_metrics" not in data
        assert "failed_metrics" not in data

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

    @parameterized.expand(
        [
            ("explicit_true", True),
            ("explicit_false", False),
        ]
    )
    def test_is_existing_round_trips_when_set(self, name: str, value: bool):
        # is_existing is required=False; when the caller populates it, it must round-trip with that value.
        data = ExperimentMetricsRecalculationSerializer({"is_existing": value}).data
        assert data["is_existing"] is value

    def test_is_existing_omitted_when_absent_from_instance(self):
        # required=False + no default means Field.get_attribute() raises SkipField() for missing attributes,
        # and the field disappears from the output entirely (rather than serializing as None). Pins the
        # contract so a future refactor — adding default=, switching to ModelSerializer, flipping required —
        # can't silently start emitting is_existing on payloads that never asked for it.
        data = ExperimentMetricsRecalculationSerializer({}).data
        assert "is_existing" not in data

    def test_result_source_defaults_to_recalculation_when_absent(self):
        # required=False + default means a real payload that never sets result_source still serializes it as
        # "recalculation", so clients can always read a concrete source.
        data = ExperimentMetricsRecalculationSerializer({"status": "completed"}).data
        assert data["result_source"] == "recalculation"

    def test_result_source_round_trips_timeseries_fallback(self):
        data = ExperimentMetricsRecalculationSerializer(
            {"status": "completed", "result_source": "timeseries_fallback"}
        ).data
        assert data["result_source"] == "timeseries_fallback"


class TestRecalculateMetricsRequestSerializer(SimpleTestCase):
    def test_defaults_trigger_to_manual_when_omitted(self):
        s = RecalculateMetricsRequestSerializer(data={})
        assert s.is_valid(), s.errors
        assert s.validated_data["trigger"] == "manual"

    @parameterized.expand(
        [
            ("manual",),
            ("cold_run",),
            ("stale_refresh",),
            ("auto_refresh",),
            ("config_change",),
            ("experiment_launch",),
            ("experiment_stop",),
            ("experiment_update",),
        ]
    )
    def test_accepts_valid_trigger(self, trigger: str):
        s = RecalculateMetricsRequestSerializer(data={"trigger": trigger})
        assert s.is_valid(), s.errors
        assert s.validated_data["trigger"] == trigger

    def test_rejects_unknown_trigger(self):
        s = RecalculateMetricsRequestSerializer(data={"trigger": "nonsense"})
        assert not s.is_valid()
        assert "trigger" in s.errors


class TestMetricRecalculationResultSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "completed",
                {"metric_uuid": "m1", "status": "completed", "result": {"variants": []}, "error_message": None},
            ),
            (
                "failed",
                {"metric_uuid": "m2", "status": "failed", "result": None, "error_message": "boom"},
            ),
            (
                "pending",
                {"metric_uuid": "m3", "status": "pending", "result": None, "error_message": None},
            ),
        ]
    )
    def test_serializes_result_row(self, name: str, payload: dict):
        data = MetricRecalculationResultSerializer(payload).data
        assert data["metric_uuid"] == payload["metric_uuid"]
        assert data["status"] == payload["status"]
        assert data["result"] == payload["result"]
        assert data["error_message"] == payload["error_message"]
