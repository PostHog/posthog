from posthog.test.base import APIBaseTest

from django.utils.timezone import now

from rest_framework import status

from products.web_analytics.backend.models import WebAnalyticsFilterPreset


class TestWebAnalyticsFilterPresetAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/web_analytics_filter_presets/{suffix}"

    def _create(self, name: str) -> WebAnalyticsFilterPreset:
        return WebAnalyticsFilterPreset.objects.create(
            team=self.team, name=name, created_by=self.user, last_modified_by=self.user
        )

    def test_invalid_order_field_returns_400(self) -> None:
        response = self.client.get(self._url() + "?order=id;drop")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_valid_order_field_sorts(self) -> None:
        self._create("beta")
        self._create("alpha")

        response = self.client.get(self._url() + "?order=name")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [preset["name"] for preset in response.json()["results"]] == ["alpha", "beta"]

    def test_tied_rows_do_not_skip_or_duplicate_across_pages(self) -> None:
        timestamp = now()
        for index in range(5):
            self._create(f"preset-{index}")
        # Force every row to share the same modified time so the sort key alone cannot order them.
        WebAnalyticsFilterPreset.objects.filter(team=self.team).update(last_modified_at=timestamp)

        seen: list[str] = []
        for offset in range(0, 5):
            response = self.client.get(self._url() + f"?limit=1&offset={offset}")
            assert response.status_code == status.HTTP_200_OK, response.json()
            seen.extend(preset["id"] for preset in response.json()["results"])

        assert len(seen) == len(set(seen)) == 5
