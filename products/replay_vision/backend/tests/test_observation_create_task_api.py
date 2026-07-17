from uuid import uuid4

from unittest.mock import patch

from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase

_HAS_ACCESS = "products.replay_vision.backend.api.observations.has_tasks_access"
_CREATE = "products.replay_vision.backend.api.observations.tasks_facade.create_task_without_run"


class TestObservationCreateTask(_VisionAPITestCase):
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
            scanner_snapshot={"name": "Rage clicks"},
            scanner_result={"model_output": {"verdict": "yes", "confidence": 0.9}, "signals_count": 1},
        )

    def _url(self) -> str:
        return f"{self.observations_url(self.scanner.id)}{self.observation.id}/create_task/"

    def test_creates_task_from_observation_and_returns_id(self) -> None:
        # Guards the observation→task contract: the scanner name reaches the title, the session reaches
        # the description, the team is scoped, and the endpoint returns the created task id.
        task_id = uuid4()
        with patch(_HAS_ACCESS, return_value=True), patch(_CREATE, return_value=task_id) as create:
            resp = self.client.post(self._url(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["task_id"], str(task_id))
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["team"], self.team)
        self.assertIn("Rage clicks", kwargs["title"])
        self.assertIn("sess-1", kwargs["description"])

    def test_requires_tasks_access(self) -> None:
        # Without PostHog Code access the endpoint must refuse and create nothing, or any observation
        # reader could mint tasks.
        with patch(_HAS_ACCESS, return_value=False), patch(_CREATE) as create:
            resp = self.client.post(self._url(), format="json")
        self.assertEqual(resp.status_code, 403, resp.content)
        create.assert_not_called()
