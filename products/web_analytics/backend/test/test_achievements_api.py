from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Team, User

from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsInteraction,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)

_VIEWSET = "products.web_analytics.backend.api.web_analytics_achievements"
_TASKS = "products.web_analytics.backend.achievements.tasks"


def _pending_keys(body: dict) -> set[tuple[str, int]]:
    return {(entry["track_key"], entry["stage"]) for entry in body["pending_celebrations"]}


class TestAchievementsAPI(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/web_analytics_achievements/{action}/"

    @patch(f"{_VIEWSET}.recompute_web_analytics_achievements_sync")
    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_record_visit_creates_one_row_per_day(self, mock_enqueue, mock_recompute) -> None:
        first = self.client.post(self._url("record_visit"))
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["recorded"])

        self.client.post(self._url("record_visit"))
        count = WebAnalyticsVisit.objects.for_team(self.team.id).filter(user=self.user).count()
        self.assertEqual(count, 1)
        self.assertTrue(mock_enqueue.called)

    @patch(f"{_VIEWSET}.recompute_web_analytics_achievements_sync")
    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_record_visit_enqueues_team_recompute(self, mock_enqueue, mock_recompute) -> None:
        response = self.client.post(self._url("record_visit"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_recompute.call_args.kwargs.get("cheap_only"))
        mock_enqueue.assert_called_once()
        self.assertIsNone(mock_enqueue.call_args.args[1])

    def test_record_interaction_recomputes_progress(self) -> None:
        with patch(f"{_TASKS}.streak_arm_for_user", return_value=None):
            response = self.client.post(self._url("record_interaction"), {"interaction_kind": "data"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        progress = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user=self.user, track_key="explorer"
        )
        self.assertEqual(progress.current_stage, 1)
        self.assertEqual(progress.progress_value, 1)
        self.assertEqual(progress.state["pending_celebrations"], [1])

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_overview_returns_six_tracks(self, mock_enqueue) -> None:
        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value="daily-only"):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(len(body["definitions"]), 6)
        self.assertIn("streak", {track["key"] for track in body["definitions"]})

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_overview_creates_team_rows_and_enqueues_when_stale(self, mock_enqueue) -> None:
        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value="daily-only"):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["team_progress"]), 2)
        team_rows = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(user__isnull=True)
        self.assertEqual({row.track_key for row in team_rows}, {"conversions", "traffic"})
        self.assertTrue(all(row.last_computed_at is None for row in team_rows))
        mock_enqueue.assert_called_once()

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_overview_control_user_creates_no_rows(self, mock_enqueue) -> None:
        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value="control"):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["team_progress"], [])
        self.assertEqual(response.json()["user_progress"], [])
        self.assertEqual(WebAnalyticsAchievementProgress.objects.for_team(self.team.id).count(), 0)
        mock_enqueue.assert_not_called()

    def test_acknowledge_celebration_is_idempotent(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="loyalty",
            current_stage=2,
            progress_value=15,
            state={"pending_celebrations": [2], "unlocked_stages": {}},
        ).save()

        first = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyalty", "stage": 2})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["acknowledged"])
        progress = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user=self.user, track_key="loyalty"
        )
        self.assertEqual(progress.state["pending_celebrations"], [])

        second = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyalty", "stage": 2})
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.json()["acknowledged"])

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_overview_is_team_scoped(self, mock_enqueue) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        WebAnalyticsAchievementProgress(
            team=other_team, user=self.user, track_key="loyalty", current_stage=3, progress_value=30, state={}
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
            track_key="loyalty",
            current_stage=2,
            progress_value=15,
            state={"pending_celebrations": [2], "unlocked_stages": {}},
        ).save()

        response = self.client.post(self._url("acknowledge_celebration"), {"track_key": "loyalty", "stage": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["acknowledged"])

        other_row = WebAnalyticsAchievementProgress.objects.for_team(other_team.id).get(
            user=self.user, track_key="loyalty"
        )
        self.assertEqual(other_row.state["pending_celebrations"], [2])

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_team_celebration_is_acknowledged_per_user(self, mock_enqueue) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="conversions",
            current_stage=1,
            progress_value=1,
            state={"pending_celebrations": [1], "unlocked_stages": {"1": "2026-06-15T00:00:00+00:00"}},
        ).save()

        def overview() -> dict:
            with patch(f"{_VIEWSET}.streak_arm_for_user", return_value=None):
                return self.client.get(self._url("overview")).json()

        # The first member sees the team celebration and acknowledges it.
        self.assertIn(("conversions", 1), _pending_keys(overview()))
        ack = self.client.post(self._url("acknowledge_celebration"), {"track_key": "conversions", "stage": 1})
        self.assertTrue(ack.json()["acknowledged"])

        # The shared row keeps the stage pending (not cleared for everyone), recording the per-user ack.
        row = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key="conversions"
        )
        self.assertEqual(row.state["pending_celebrations"], [1])
        self.assertEqual(row.state["celebration_acks"]["1"], [self.user.id])

        # The acking member no longer sees it; a second member still does.
        self.assertNotIn(("conversions", 1), _pending_keys(overview()))
        other = User.objects.create_and_join(self.organization, "second@example.com", None)
        self.client.force_login(other)
        self.assertIn(("conversions", 1), _pending_keys(overview()))

    @patch(f"{_VIEWSET}.enqueue_recompute_web_analytics_achievements_debounced")
    def test_overview_exposes_stage_unlock_timestamps(self, mock_enqueue) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="loyalty",
            current_stage=2,
            progress_value=15,
            state={
                "unlocked_stages": {
                    "1": "2026-06-10T00:00:00+00:00",
                    "2": "2026-06-15T00:00:00+00:00",
                }
            },
        ).save()

        with patch(f"{_VIEWSET}.streak_arm_for_user", return_value=None):
            response = self.client.get(self._url("overview"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        loyalty = next(row for row in response.json()["user_progress"] if row["track_key"] == "loyalty")
        self.assertEqual(set(loyalty["unlocked_at"].keys()), {"1", "2"})
        self.assertTrue(loyalty["unlocked_at"]["2"].startswith("2026-06-15"))

    @patch(f"{_VIEWSET}.recompute_web_analytics_achievements_sync")
    def test_record_interaction_increments_counter(self, mock_recompute) -> None:
        first = self.client.post(self._url("record_interaction"), {"interaction_kind": "data"})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.json()["recorded"])
        self.client.post(self._url("record_interaction"), {"interaction_kind": "data"})

        interaction = WebAnalyticsInteraction.objects.for_team(self.team.id).get(user=self.user, kind="data")
        self.assertEqual(interaction.count, 2)

    def test_record_interaction_rejects_unknown_kind(self) -> None:
        response = self.client.post(self._url("record_interaction"), {"interaction_kind": "bogus"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preferences_default_is_not_opted_out(self) -> None:
        response = self.client.get(self._url("preferences"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["achievements_opt_out"])

    def test_preferences_round_trip(self) -> None:
        opt_out = self.client.post(self._url("preferences"), {"achievements_opt_out": True})
        self.assertEqual(opt_out.status_code, status.HTTP_200_OK)
        self.assertTrue(opt_out.json()["achievements_opt_out"])
        self.assertTrue(self.client.get(self._url("preferences")).json()["achievements_opt_out"])

        opt_in = self.client.post(self._url("preferences"), {"achievements_opt_out": False})
        self.assertFalse(opt_in.json()["achievements_opt_out"])
        self.assertFalse(self.client.get(self._url("preferences")).json()["achievements_opt_out"])

    def test_preferences_are_scoped_per_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self.client.post(self._url("preferences"), {"achievements_opt_out": True})

        other_url = f"/api/projects/{other_team.id}/web_analytics_achievements/preferences/"
        self.assertFalse(self.client.get(other_url).json()["achievements_opt_out"])
        self.assertEqual(
            WebAnalyticsUserConfig.objects.for_team(self.team.id).filter(user=self.user).count(),
            1,
        )
