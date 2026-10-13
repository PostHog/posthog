from django.utils import timezone

from parameterized import parameterized

from posthog.models import User

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestObservationViewed(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="sess-1",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={
                "model_output": {"verdict": "no", "confidence": 0.9, "scanner_type": "monitor"},
                "signals_count": 0,
            },
        )

    @parameterized.expand(
        [
            ("scanner route", lambda self: f"{self.observations_url(self.scanner.id)}{self.observation.id}/"),
            (
                "session route",
                lambda self: f"/api/environments/{self.team.id}/vision/observations/{self.observation.id}/",
            ),
        ]
    )
    def test_viewed_is_recorded_per_user(self, _name: str, detail_url) -> None:
        url = detail_url(self)
        assert self.client.get(url).json()["viewed"] is False

        assert self.client.post(f"{url}viewed/").status_code == 204
        assert self.client.get(url).json()["viewed"] is True
        assert self.client.get(self.observations_url(self.scanner.id)).json()["results"][0]["viewed"] is True

        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        self.client.force_login(other)
        assert self.client.get(url).json()["viewed"] is False
