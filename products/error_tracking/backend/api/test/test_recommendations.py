from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType

from products.error_tracking.backend.models import ErrorTrackingRecommendation

MOCK_CROSS_SELL_META = {"products": [{"key": "session_replay", "enabled": False}, {"key": "logs", "enabled": False}]}
MOCK_CROSS_SELL_META_UPDATED = {
    "products": [{"key": "session_replay", "enabled": True}, {"key": "logs", "enabled": True}]
}
MOCK_ALERTS_META = {
    "alerts": [
        {"key": "issue_created", "enabled": False},
        {"key": "issue_reopened", "enabled": False},
        {"key": "issue_spiking", "enabled": False},
    ]
}


class TestRecommendationsAPI(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    def _result_by_type(self, response, type_):
        return next(r for r in response.json()["results"] if r["type"] == type_)

    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_first_list_creates_recommendations(self, mock_cross_sell_compute, mock_alerts_compute):
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 2)
        self.assertEqual(self._result_by_type(response, "cross_sell")["meta"], MOCK_CROSS_SELL_META)
        self.assertEqual(self._result_by_type(response, "alerts")["meta"], MOCK_ALERTS_META)
        mock_cross_sell_compute.assert_called_once()
        mock_alerts_compute.assert_called_once()

    @patch(
        "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute",
        return_value=MOCK_ALERTS_META,
    )
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_second_list_within_interval_does_not_recompute(self, mock_cross_sell_compute, mock_alerts_compute):
        self._list()
        mock_cross_sell_compute.assert_called_once()
        mock_alerts_compute.assert_called_once()

        self._list()
        mock_cross_sell_compute.assert_called_once()
        mock_alerts_compute.assert_called_once()

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch("products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute")
    @patch("products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute")
    def test_refresh_before_interval_returns_cached(self, mock_cross_sell_compute, mock_alerts_compute, frozen_time):
        mock_cross_sell_compute.return_value = MOCK_CROSS_SELL_META
        mock_alerts_compute.return_value = MOCK_ALERTS_META
        response = self._list()
        rec_id = self._result_by_type(response, "cross_sell")["id"]
        mock_cross_sell_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=10))
        mock_cross_sell_compute.return_value = MOCK_CROSS_SELL_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_CROSS_SELL_META)
        mock_cross_sell_compute.assert_not_called()

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch("products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute")
    @patch("products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute")
    def test_refresh_after_interval_recomputes(self, mock_cross_sell_compute, mock_alerts_compute, frozen_time):
        mock_cross_sell_compute.return_value = MOCK_CROSS_SELL_META
        mock_alerts_compute.return_value = MOCK_ALERTS_META
        response = self._list()
        rec_id = self._result_by_type(response, "cross_sell")["id"]
        mock_cross_sell_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=31))
        mock_cross_sell_compute.return_value = MOCK_CROSS_SELL_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_CROSS_SELL_META_UPDATED)
        mock_cross_sell_compute.assert_called_once()


class TestAlertsRecommendation(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _create_alert(self, event: str, *, deleted: bool = False, type: str = HogFunctionType.INTERNAL_DESTINATION):
        return HogFunction.objects.create(
            team=self.team,
            name=f"Alert for {event}",
            type=type,
            deleted=deleted,
            hog="",
            filters={"events": [{"id": event, "type": "events"}]},
        )

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_no_alerts_set_up(self, _mock_cross_sell):
        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        alerts_meta = next(r["meta"] for r in response.json()["results"] if r["type"] == "alerts")
        self.assertEqual(
            alerts_meta,
            {
                "alerts": [
                    {"key": "issue_created", "enabled": False},
                    {"key": "issue_reopened", "enabled": False},
                    {"key": "issue_spiking", "enabled": False},
                ]
            },
        )

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_detects_each_alert_type(self, _mock_cross_sell):
        self._create_alert("$error_tracking_issue_created")
        self._create_alert("$error_tracking_issue_reopened")
        self._create_alert("$error_tracking_issue_spiking")

        response = self._list()

        alerts_meta = next(r["meta"] for r in response.json()["results"] if r["type"] == "alerts")
        self.assertEqual(
            alerts_meta,
            {
                "alerts": [
                    {"key": "issue_created", "enabled": True},
                    {"key": "issue_reopened", "enabled": True},
                    {"key": "issue_spiking", "enabled": True},
                ]
            },
        )

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_ignores_deleted_alerts(self, _mock_cross_sell):
        self._create_alert("$error_tracking_issue_created", deleted=True)

        response = self._list()

        alerts_meta = next(r["meta"] for r in response.json()["results"] if r["type"] == "alerts")
        self.assertFalse(alerts_meta["alerts"][0]["enabled"])

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_CROSS_SELL_META,
    )
    def test_ignores_non_internal_destination_alerts(self, _mock_cross_sell):
        self._create_alert("$error_tracking_issue_created", type=HogFunctionType.DESTINATION)

        response = self._list()

        alerts_meta = next(r["meta"] for r in response.json()["results"] if r["type"] == "alerts")
        self.assertFalse(alerts_meta["alerts"][0]["enabled"])
