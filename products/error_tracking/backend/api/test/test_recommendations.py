from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingRecommendation

MOCK_META = {"products": [{"key": "session_replay", "enabled": False}, {"key": "logs", "enabled": False}]}
MOCK_META_UPDATED = {"products": [{"key": "session_replay", "enabled": True}, {"key": "logs", "enabled": True}]}


class TestRecommendationsAPI(APIBaseTest):
    def _list(self):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/recommendations/")

    def _refresh(self, rec_id):
        return self.client.post(f"/api/environments/{self.team.id}/error_tracking/recommendations/{rec_id}/refresh/")

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_first_list_creates_recommendations(self, mock_compute):
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 0)

        response = self._list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ErrorTrackingRecommendation.objects.filter(team=self.team).count(), 1)
        self.assertEqual(response.json()["results"][0]["meta"], MOCK_META)
        mock_compute.assert_called_once()

    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
        return_value=MOCK_META,
    )
    def test_second_list_within_interval_does_not_recompute(self, mock_compute):
        self._list()
        mock_compute.assert_called_once()

        self._list()
        mock_compute.assert_called_once()

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_before_interval_returns_cached(self, mock_compute, frozen_time):
        mock_compute.return_value = MOCK_META
        response = self._list()
        rec_id = response.json()["results"][0]["id"]
        mock_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=10))
        mock_compute.return_value = MOCK_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_META)
        mock_compute.assert_not_called()

    @freeze_time("2026-01-01T00:00:00Z", as_kwarg="frozen_time")
    @patch(
        "products.error_tracking.backend.recommendations.cross_sell.CrossSellRecommendation.compute",
    )
    def test_refresh_after_interval_recomputes(self, mock_compute, frozen_time):
        mock_compute.return_value = MOCK_META
        response = self._list()
        rec_id = response.json()["results"][0]["id"]
        mock_compute.reset_mock()

        frozen_time.tick(timedelta(seconds=31))
        mock_compute.return_value = MOCK_META_UPDATED
        response = self._refresh(rec_id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["meta"], MOCK_META_UPDATED)
        mock_compute.assert_called_once()
