from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Team, User

from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsInteraction,
    WebAnalyticsVisit,
)

_VIEWSET = "products.web_analytics.backend.api.web_analytics_achievements"


def _pending_keys(body: dict) -> set[tuple[str, int]]:
    return {(entry["track_key"], entry["stage"]) for entry in body["pending_celebrations"]}


class TestAchievementsAPI(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/web_analytics_achievements/{action}/"

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_record_visit_creates_one_row_per_day(self, mock_enqueue) -> None:
        first = self.client.post(self._url("record_visit"))
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["recorded"])

        self.client.post(self._url("record_visit"))
        count = WebAnalyticsVisit.objects.for_team(self.team.id).filter(user=self.user).count()
        self.assertEqual(count, 1)
        self.assertTrue(mock_enqueue.called)

    def test_overview_returns_six_tracks(self) -> None:
        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value="daily-only"):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(len(body["definitions"]), 6)
        self.assertIn("hog_streak", {track["key"] for track in body["definitions"]})

    def test_acknowledge_celebration_is_idempotent(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="loyal_hog",
            current_stage=2,
            progress_value=15,
            state={"pending_celebrations": [2], "unlocked_stages": {}},
        ).save()

        first = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyal_hog", "stage": 2})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["acknowledged"])
        progress = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user=self.user, track_key="loyal_hog"
        )
        self.assertEqual(progress.state["pending_celebrations"], [])

        second = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyal_hog", "stage": 2})
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.json()["acknowledged"])

    def test_overview_is_team_scoped(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        WebAnalyticsAchievementProgress(
            team=other_team, user=self.user, track_key="loyal_hog", current_stage=3, progress_value=30, state={}
        ).save()
        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value=None):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["user_progress"], [])

    def test_acknowledge_celebration_is_team_scoped(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        WebAnalyticsAchievementProgress(
            team=other_team,
            user=self.user,
            track_key="loyal_hog",
            current_stage=2,
            progress_value=15,
            state={"pending_celebrations": [2], "unlocked_stages": {}},
        ).save()

        response = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyal_hog", "stage": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["acknowledged"])

        other_row = WebAnalyticsAchievementProgress.objects.for_team(other_team.id).get(
            user=self.user, track_key="loyal_hog"
        )
        self.assertEqual(other_row.state["pending_celebrations"], [2])

    def test_team_celebration_is_acknowledged_per_user(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="goal_hog",
            current_stage=1,
            progress_value=1,
            state={"pending_celebrations": [1], "unlocked_stages": {"1": "2026-06-15T00:00:00+00:00"}},
        ).save()

        def overview() -> dict:
            with patch(f"{_VIEWSET}.streak_arm_for_user", return_value=None):
                return self.client.get(self._url("overview")).json()

        # The first member sees the team celebration and acknowledges it.
        self.assertIn(("goal_hog", 1), _pending_keys(overview()))
        ack = self.client.post(self._url("acknowledge_celebration"), {"track_key": "goal_hog", "stage": 1})
        self.assertTrue(ack.json()["acknowledged"])

        # The shared row keeps the stage pending (not cleared for everyone), recording the per-user ack.
        row = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key="goal_hog"
        )
        self.assertEqual(row.state["pending_celebrations"], [1])
        self.assertEqual(row.state["celebration_acks"]["1"], [self.user.id])

        # The acking member no longer sees it; a second member still does.
        self.assertNotIn(("goal_hog", 1), _pending_keys(overview()))
        other = User.objects.create_and_join(self.organization, "second@example.com", None)
        self.client.force_login(other)
        self.assertIn(("goal_hog", 1), _pending_keys(overview()))

    def test_record_interaction_increments_counter(self) -> None:
        first = self.client.post(self._url("record_interaction"), {"interaction_kind": "data"})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["recorded"])
        self.client.post(self._url("record_interaction"), {"interaction_kind": "data"})

        interaction = WebAnalyticsInteraction.objects.for_team(self.team.id).get(user=self.user, kind="data")
        self.assertEqual(interaction.count, 2)

    def test_record_interaction_rejects_unknown_kind(self) -> None:
        response = self.client.post(self._url("record_interaction"), {"interaction_kind": "bogus"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
