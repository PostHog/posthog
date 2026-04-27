from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.hog_functions.hog_function import HogFunction

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations.alerts import AlertsRecommendation

MOCK_META = {"products": [{"key": "session_replay", "enabled": False}, {"key": "logs", "enabled": False}]}
MOCK_META_UPDATED = {"products": [{"key": "session_replay", "enabled": True}, {"key": "logs", "enabled": True}]}
MOCK_ALERTS_META = {
    "alerts": [
        {"key": "error-tracking-issue-created", "enabled": False},
        {"key": "error-tracking-issue-reopened", "enabled": False},
        {"key": "error-tracking-issue-spiking", "enabled": False},
    ]
}


class TestRecommendationsAPI(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_first_list_creates_recommendations(self, mock_compute, mock_alerts_compute):
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 2)
        results = response.json()["results"]
        by_type = {r["type"]: r for r in results}
        self.assertEqual(by_type["cross_sell"]["meta"], MOCK_META)
        self.assertEqual(by_type["alerts"]["meta"], MOCK_ALERTS_META)
        mock_compute.assert_called_once()
        mock_alerts_compute.assert_called_once()

    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_second_list_within_interval_does_not_recompute(self, mock_compute, mock_alerts_compute):
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
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_before_interval_returns_cached(self, mock_compute, mock_alerts_compute, frozen_time):
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
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_after_interval_recomputes(self, mock_compute, mock_alerts_compute, frozen_time):
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
