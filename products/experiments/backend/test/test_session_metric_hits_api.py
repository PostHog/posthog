import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.serializers import (
    MAX_SESSION_METRIC_HITS_SESSIONS,
    SessionMetricHitsRequestSerializer,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl


def _metric(event: str, name: str) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": str(uuid.uuid4()),
        "name": name,
        "source": {"kind": "EventsNode", "event": event},
    }


class TestSessionMetricHitsRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", {}),
            ("empty", {"session_ids": []}),
            ("over_limit", {"session_ids": [f"s{i}" for i in range(MAX_SESSION_METRIC_HITS_SESSIONS + 1)]}),
            ("blank_entry", {"session_ids": [""]}),
            ("non_string_entry", {"session_ids": [{"id": "s1"}]}),
        ]
    )
    def test_invalid_bodies_rejected(self, _name: str, body: dict[str, Any]) -> None:
        serializer = SessionMetricHitsRequestSerializer(data=body)
        assert not serializer.is_valid()
        assert "session_ids" in serializer.errors


@freeze_time("2026-01-02T12:00:00Z")
class TestSessionMetricHitsAPI(ClickhouseTestMixin, APILicensedTest):
    def _create_experiment(
        self,
        metrics: Optional[list[dict[str, Any]]] = None,
        team: Optional[Team] = None,
        start_date: Optional[datetime] = datetime(2025, 12, 1, tzinfo=UTC),
    ) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team,
            created_by=self.user,
            key=f"flag-{uuid.uuid4().hex[:8]}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        return Experiment.objects.create(
            team=team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            start_date=start_date,
            metrics=metrics or [_metric("purchase", "Purchases"), _metric("signup", "Signups")],
        )

    def _create_session_event(self, event: str, session_id: str, timestamp: str = "2026-01-01T10:05:00Z") -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id="user1",
            timestamp=timestamp,
            properties={"$session_id": session_id},
        )

    def _post(self, experiment: Experiment, session_ids: list[Any]) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}/session_metric_hits/",
            {"session_ids": session_ids},
            format="json",
        )

    def test_returns_hits_per_session_omitting_sessions_without_hits(self) -> None:
        metric_a = _metric("purchase", "Purchases")
        metric_b = _metric("signup", "Signups")
        experiment = self._create_experiment(metrics=[metric_a, metric_b])
        self._create_session_event("purchase", "s1", timestamp="2026-01-01T10:05:00Z")
        self._create_session_event("purchase", "s1", timestamp="2026-01-01T10:10:00Z")
        self._create_session_event("signup", "s2", timestamp="2026-01-01T10:07:00Z")
        flush_persons_and_events()

        response = self._post(experiment, ["s1", "s2", "s3"])

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert set(results) == {"s1", "s2"}
        assert results["s1"] == [
            {
                "metric_uuid": metric_a["uuid"],
                "metric_name": "Purchases",
                "event_count": 2,
                "first_timestamp": "2026-01-01T10:05:00Z",
            }
        ]
        assert [hit["metric_uuid"] for hit in results["s2"]] == [metric_b["uuid"]]

    def test_invalid_body_rejected_with_400(self) -> None:
        experiment = self._create_experiment()
        response = self._post(experiment, [])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_draft_experiment_rejected_with_400(self) -> None:
        experiment = self._create_experiment(start_date=None)
        response = self._post(experiment, ["s1"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_404_for_other_teams_experiment(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        experiment = self._create_experiment(team=other_team)
        response = self._post(experiment, ["s1"])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_403_without_session_recording_resource_access(self) -> None:
        features = self.organization.available_product_features or []
        features.append({"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL})
        self.organization.available_product_features = features
        self.organization.save()
        AccessControl.objects.create(team=self.team, resource="session_recording", access_level="none")
        experiment = self._create_experiment()

        response = self._post(experiment, ["s1"])

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_requires_session_recording_read_scope(self) -> None:
        experiment = self._create_experiment()
        self.client.logout()

        def _personal_api_key(scopes: list[str]) -> str:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="t", secure_value=hash_key_value(token), scopes=scopes)
            return token

        url = f"/api/projects/{self.team.id}/experiments/{experiment.id}/session_metric_hits/"
        response = self.client.post(
            url,
            {"session_ids": ["s1"]},
            format="json",
            headers={"authorization": f"Bearer {_personal_api_key(['experiment:read'])}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = self.client.post(
            url,
            {"session_ids": ["s1"]},
            format="json",
            headers={"authorization": f"Bearer {_personal_api_key(['experiment:read', 'session_recording:read'])}"},
        )
        assert response.status_code == status.HTTP_200_OK
