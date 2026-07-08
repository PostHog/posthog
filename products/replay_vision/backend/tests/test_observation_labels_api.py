from datetime import timedelta
from typing import Any

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

    def test_quality_flag_off_hides_label_endpoints_but_not_reads(self) -> None:
        # `replay-vision-quality` gates ratings even when product-level `replay-vision` is on.
        def _flags(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key != "replay-vision-quality"

        with patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", side_effect=_flags):
            post_resp = self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")
            delete_resp = self.client.delete(self._label_url(self.observation))
            read_resp = self.client.get(self._retrieve_url(self.observation))
        self.assertEqual(post_resp.status_code, 404, post_resp.content)
        self.assertEqual(delete_resp.status_code, 404, delete_resp.content)
        self.assertEqual(read_resp.status_code, 200, read_resp.content)

    def test_label_write_denied_without_scanner_editor_access_on_session_route(self) -> None:
        # The session route's get_object only checks the observation row; label writes must object-check the scanner.
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=lambda obj, required_level=None, **_: not isinstance(obj, ReplayScanner),
        ):
            resp = self.client.post(
                f"/api/environments/{self.team.id}/vision/observations/{self.observation.id}/label/",
                {"is_correct": True},
                format="json",
            )
        self.assertEqual(resp.status_code, 403, resp.json())
        self.assertFalse(ReplayObservationLabel.objects.filter(observation=self.observation).exists())

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

    def test_labeled_filter_splits_labeled_from_unlabeled(self) -> None:
        unlabeled = self._create_observation(self.scanner, "sess-2")
        self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")

        base_url = self.observations_url(self.scanner.id)
        labeled_ids = {r["id"] for r in self.client.get(f"{base_url}?labeled=true").json()["results"]}
        self.assertEqual(labeled_ids, {str(self.observation.id)})
        unlabeled_ids = {r["id"] for r in self.client.get(f"{base_url}?labeled=false").json()["results"]}
        self.assertEqual(unlabeled_ids, {str(unlabeled.id)})

    def test_stats_label_aggregates_split_by_day_and_direction(self) -> None:
        same_day_down = self._create_observation(self.scanner, "sess-down-today")
        earlier = self._create_observation(self.scanner, "sess-down-earlier")
        outside_window = self._create_observation(self.scanner, "sess-up-old")
        window_edge = self._create_observation(self.scanner, "sess-down-window-edge")
        just_outside = self._create_observation(self.scanner, "sess-down-just-outside")
        self._create_observation(self.scanner, "sess-unlabeled")
        # created_at is auto_now_add, so pin every row from one captured `now` (midnight-safe) via update.
        now = timezone.now().replace(hour=12)
        ReplayObservation.objects.filter(id__in=[self.observation.id, same_day_down.id]).update(created_at=now)
        ReplayObservation.objects.filter(id=earlier.id).update(created_at=now - timedelta(days=3))
        ReplayObservation.objects.filter(id=outside_window.id).update(created_at=now - timedelta(days=40))
        # The window is `recent_days` calendar days ending today: day 13 is the first charted bar, day 14 is out.
        ReplayObservation.objects.filter(id=window_edge.id).update(created_at=now - timedelta(days=13))
        ReplayObservation.objects.filter(id=just_outside.id).update(created_at=now - timedelta(days=14))
        # Prompt-version snapshots: v1 on the older observation, v2 on today's, so markers show the change.
        ReplayObservation.objects.filter(id=earlier.id).update(
            scanner_snapshot={"scanner_version": 1, "scanner_config": {"prompt": "v1 prompt"}}
        )
        ReplayObservation.objects.filter(id__in=[self.observation.id, same_day_down.id]).update(
            scanner_snapshot={"scanner_version": 2, "scanner_config": {"prompt": "v2 prompt"}}
        )
        self.client.post(self._label_url(self.observation), {"is_correct": True}, format="json")
        for observation in (same_day_down, earlier, outside_window, window_edge, just_outside):
            is_correct = observation is outside_window
            self.client.post(self._label_url(observation), {"is_correct": is_correct}, format="json")
        # Ratings all happened "now". Pin updated_at for by_rating_day, since queryset update bypasses auto_now.
        ReplayObservationLabel.objects.all().update(updated_at=now)

        labels = self.client.get(f"{self.observations_url(self.scanner.id)}stats/?recent_days=14").json()["labels"]

        # Totals span the whole filtered set; by_day only covers the recent window.
        self.assertEqual(labels["up_total"], 2)
        self.assertEqual(labels["down_total"], 4)
        self.assertEqual(
            labels["by_day"],
            [
                {"date": (now - timedelta(days=13)).date().isoformat(), "up": 0, "down": 1},
                {"date": (now - timedelta(days=3)).date().isoformat(), "up": 0, "down": 1},
                {"date": now.date().isoformat(), "up": 1, "down": 1},
            ],
        )
        # All six ratings were given today, including those on out-of-window observations.
        self.assertEqual(labels["by_rating_day"], [{"date": now.date().isoformat(), "up": 2, "down": 4}])
        self.assertEqual(
            labels["version_markers"],
            [
                {
                    "date": (now - timedelta(days=3)).date().isoformat(),
                    "version": 1,
                    "prompt": "v1 prompt",
                    "up": 0,
                    "down": 1,
                },
                {
                    "date": now.date().isoformat(),
                    "version": 2,
                    "prompt": "v2 prompt",
                    "up": 1,
                    "down": 1,
                },
            ],
        )

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
