from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.hog_functions.hog_function import HogFunction

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations.alerts import AlertsRecommendation
from products.error_tracking.backend.recommendations.weekly_digest import WeeklyDigestRecommendation

MOCK_META = {"products": [{"key": "session_replay", "enabled": False}, {"key": "logs", "enabled": False}]}
MOCK_META_UPDATED = {"products": [{"key": "session_replay", "enabled": True}, {"key": "logs", "enabled": True}]}
MOCK_ALERTS_META = {
    "alerts": [
        {"key": "error-tracking-issue-created", "enabled": False},
        {"key": "error-tracking-issue-reopened", "enabled": False},
        {"key": "error-tracking-issue-spiking", "enabled": False},
    ]
}
MOCK_WEEKLY_DIGEST_META = {"enabled": False}


class TestRecommendationsAPI(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @patch(
        "products.error_tracking.backend.recommendations.weekly_digest.WeeklyDigestRecommendation.compute",
        return_value=MOCK_WEEKLY_DIGEST_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_first_list_creates_recommendations(self, mock_compute, mock_alerts_compute, mock_weekly_digest_compute):
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 3)
        results = response.json()["results"]
        by_type = {r["type"]: r for r in results}
        self.assertEqual(by_type["cross_sell"]["meta"], MOCK_META)
        self.assertEqual(by_type["alerts"]["meta"], MOCK_ALERTS_META)
        self.assertEqual(by_type["weekly_digest"]["meta"], MOCK_WEEKLY_DIGEST_META)
        mock_compute.assert_called_once()
        mock_alerts_compute.assert_called_once()
        mock_weekly_digest_compute.assert_called_once()

    @patch(
        "products.error_tracking.backend.recommendations.weekly_digest.WeeklyDigestRecommendation.compute",
        return_value=MOCK_WEEKLY_DIGEST_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_second_list_within_interval_does_not_recompute(
        self, mock_compute, mock_alerts_compute, mock_weekly_digest_compute
    ):
        self._list()
        mock_compute.assert_called_once()

        self._list()
        mock_compute.assert_called_once()

    def test_alerts_recommendation_detects_existing_alerts(self):
        HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            filters={"events": [{"id": "$error_tracking_issue_created", "type": "events"}]},
            hog="return event",
        )
        meta = AlertsRecommendation().compute(self.team)
        by_key = {a["key"]: a["enabled"] for a in meta["alerts"]}
        self.assertTrue(by_key["error-tracking-issue-created"])
        self.assertFalse(by_key["error-tracking-issue-reopened"])
        self.assertFalse(by_key["error-tracking-issue-spiking"])

    def test_alerts_recommendation_ignores_deleted_alerts(self):
        HogFunction.objects.create(
            team=self.team,
            type="internal_destination",
            filters={"events": [{"id": "$error_tracking_issue_created", "type": "events"}]},
            hog="return event",
            deleted=True,
        )
        meta = AlertsRecommendation().compute(self.team)
        by_key = {a["key"]: a["enabled"] for a in meta["alerts"]}
        self.assertFalse(by_key["error-tracking-issue-created"])

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch(
        "products.error_tracking.backend.recommendations.weekly_digest.WeeklyDigestRecommendation.compute",
        return_value=MOCK_WEEKLY_DIGEST_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_before_interval_returns_cached(
        self, mock_compute, mock_alerts_compute, mock_weekly_digest_compute, frozen_time
    ):
        mock_compute.return_value = MOCK_META
        response = self._list()
        cross_sell_rec = next(r for r in response.json()["results"] if r["type"] == "cross_sell")
        rec_id = cross_sell_rec["id"]
        mock_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=10))
        mock_compute.return_value = MOCK_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_META)
        mock_compute.assert_not_called()

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch(
        "products.error_tracking.backend.recommendations.weekly_digest.WeeklyDigestRecommendation.compute",
        return_value=MOCK_WEEKLY_DIGEST_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_after_interval_recomputes(
        self, mock_compute, mock_alerts_compute, mock_weekly_digest_compute, frozen_time
    ):
        mock_compute.return_value = MOCK_META
        response = self._list()
        cross_sell_rec = next(r for r in response.json()["results"] if r["type"] == "cross_sell")
        rec_id = cross_sell_rec["id"]
        mock_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=31))
        mock_compute.return_value = MOCK_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_META_UPDATED)
        mock_compute.assert_called_once()

    def test_weekly_digest_recommendation_reflects_user_notification_settings(self):
        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest": True,
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        self.assertTrue(WeeklyDigestRecommendation().compute(self.team, self.user)["enabled"])

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest": False,
        }
        self.user.save()
        self.assertFalse(WeeklyDigestRecommendation().compute(self.team, self.user)["enabled"])

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest": True,
            "error_tracking_weekly_digest_project_enabled": {},
        }
        self.user.save()
        self.assertFalse(WeeklyDigestRecommendation().compute(self.team, self.user)["enabled"])

    def test_weekly_digest_recommendation_ignores_global_weekly_digest_kill_switch(self):
        # Even though `all_weekly_digest_disabled` is True, we treat the ET digest
        # as enabled because the user has the ET-specific toggle + project on.
        self.user.partial_notification_settings = {
            "all_weekly_digest_disabled": True,
            "error_tracking_weekly_digest": True,
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        self.assertTrue(WeeklyDigestRecommendation().compute(self.team, self.user)["enabled"])

    @patch(
        "products.error_tracking.backend.recommendations.weekly_digest.WeeklyDigestRecommendation.compute",
        return_value=MOCK_WEEKLY_DIGEST_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_weekly_digest_is_user_scoped_and_not_visible_to_other_users(
        self, mock_compute, mock_alerts_compute, mock_weekly_digest_compute
    ):
        from posthog.models.organization import OrganizationMembership
        from posthog.models.user import User

        other_user = User.objects.create_user(email="other@posthog.com", password=None, first_name="Other")
        OrganizationMembership.objects.create(user=other_user, organization=self.organization)

        self._list()

        # The requesting user gets a weekly_digest row for themselves...
        self.assertEqual(
            ErrorTrackingRecommendation.objects.filter(team=self.team, type="weekly_digest", user=self.user).count(),
            1,
        )
        # ...but no team-wide (user=NULL) weekly_digest row is created.
        self.assertFalse(
            ErrorTrackingRecommendation.objects.filter(team=self.team, type="weekly_digest", user__isnull=True).exists()
        )

        # Manually seed a weekly_digest for the other user — the requesting user must not see it.
        other_rec = ErrorTrackingRecommendation.objects.create(
            team=self.team, user=other_user, type="weekly_digest", meta={"enabled": True}
        )
        response = self._list()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in response.json()["results"]}
        self.assertNotIn(str(other_rec.id), ids)
