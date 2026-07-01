from unittest.mock import patch

from django.utils import timezone

from posthog.models import User

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase


class TestObservationLabels(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.observation = self._create_observation(self.scanner, "sess-1")

    def _create_observation(self, scanner: ReplayScanner, session_id: str) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.ON_DEMAND,
            scanner_result={
                "model_output": {"verdict": "no", "confidence": 0.9, "scanner_type": "monitor"},
                "signals_count": 0,
            },
        )

    def _label_url(self, observation: ReplayObservation) -> str:
        return f"{self.observations_url(self.scanner.id)}{observation.id}/label/"

    def _retrieve_url(self, observation: ReplayObservation) -> str:
        return f"{self.observations_url(self.scanner.id)}{observation.id}/"

    def test_upsert_and_label_roundtrip(self) -> None:
        self.assertIsNone(self.client.get(self._retrieve_url(self.observation)).json()["label"])

        resp = self.client.post(
            self._label_url(self.observation), {"is_correct": False, "feedback": "should be yes"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ReplayObservationLabel.objects.filter(observation=self.observation).count(), 1)

        label = self.client.get(self._retrieve_url(self.observation)).json()["label"]
        self.assertEqual(label, {"is_correct": False, "feedback": "should be yes"})

    def test_relabeling_updates_the_single_shared_label(self) -> None:
        self.client.post(self._label_url(self.observation), {"is_correct": False, "feedback": "wrong"}, format="json")
        self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")

        labels = ReplayObservationLabel.objects.filter(observation=self.observation)
        self.assertEqual(labels.count(), 1)
        label = labels.first()
        assert label is not None
        self.assertTrue(label.is_correct)
        self.assertEqual(label.feedback, "")

    def test_feedback_is_length_bounded(self) -> None:
        resp = self.client.post(
            self._label_url(self.observation),
            {"is_correct": False, "feedback": "x" * 5001},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_removes_label(self) -> None:
        self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")
        resp = self.client.delete(self._label_url(self.observation))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ReplayObservationLabel.objects.filter(observation=self.observation).exists())

    def test_labeled_filter_excludes_unlabeled(self) -> None:
        unlabeled = self._create_observation(self.scanner, "sess-2")
        self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")

        results = self.client.get(f"{self.observations_url(self.scanner.id)}?labeled=true").json()["results"]
        ids = {r["id"] for r in results}
        self.assertIn(str(self.observation.id), ids)
        self.assertNotIn(str(unlabeled.id), ids)

    def test_order_by_label_groups_labeled_with_unlabeled_last(self) -> None:
        correct_obs = self._create_observation(self.scanner, "sess-correct")
        self._create_observation(self.scanner, "sess-unlabeled")
        self.client.post(self._label_url(self.observation), {"is_correct": False, "feedback": "wrong"}, format="json")
        self.client.post(self._label_url(correct_obs), {"is_correct": True}, format="json")

        results = self.client.get(f"{self.observations_url(self.scanner.id)}?order_by=label").json()["results"]
        # Ascending: incorrect (false) then correct (true), with the unlabeled row last regardless.
        self.assertEqual([r["session_id"] for r in results], ["sess-1", "sess-correct", "sess-unlabeled"])

    def test_label_is_shared_not_scoped_to_a_user(self) -> None:
        # A label another user set is visible to everyone — there are no personal versions.
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        ReplayObservationLabel.objects.create(
            observation=self.observation, created_by=other_user, is_correct=False, feedback="shared feedback"
        )
        label = self.client.get(self._retrieve_url(self.observation)).json()["label"]
        self.assertEqual(label, {"is_correct": False, "feedback": "shared feedback"})

    def _deny_editor(self):
        # Viewer access still passes (reading observations); only editor is withheld.
        return patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, required_level=None, **_: required_level != "editor",
        )

    def test_editing_label_requires_editor_access(self) -> None:
        with self._deny_editor():
            post = self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")
            delete = self.client.delete(self._label_url(self.observation))
        self.assertEqual(post.status_code, 403, post.json())
        self.assertEqual(delete.status_code, 403)
        self.assertFalse(ReplayObservationLabel.objects.filter(observation=self.observation).exists())
