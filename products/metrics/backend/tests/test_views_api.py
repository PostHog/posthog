from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.metrics.backend.models import MetricsView


class TestMetricsViewAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/metrics/views/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _create_via_api(self, **overrides) -> dict:
        payload = {
            "name": "Error rate by service",
            "filters": {"metricName": "http_requests_total", "aggregation": "rate"},
            **overrides,
        }
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_create_and_retrieve(self):
        created = self._create_via_api()
        assert created["filters"] == {"metricName": "http_requests_total", "aggregation": "rate"}
        assert created["created_by"]["id"] == self.user.pk
        assert created["short_id"]

        response = self.client.get(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Error rate by service"

    def test_list_only_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        MetricsView.objects.unscoped().create(team=team2, name="Other team view", created_by=self.user)
        self._create_via_api(name="My view")

        response = self.client.get(self.base_url)
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "My view"

    @parameterized.expand(
        [
            ("retrieve", "get", None),
            ("update", "patch", {"name": "Hacked"}),
            ("delete", "delete", None),
        ]
    )
    def test_cannot_access_other_teams_view(self, _label, method, payload):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = MetricsView.objects.unscoped().create(team=team2, name="Other", created_by=self.user)

        response = getattr(self.client, method)(f"{self.base_url}{other_view.short_id}/", payload, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_view.refresh_from_db()
        assert other_view.name == "Other"

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_returns_403_when_feature_flag_disabled(self, _mock_feature_enabled):
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("too_deep",),
            ("too_large",),
        ]
    )
    def test_rejects_out_of_bounds_filters(self, label):
        if label == "too_deep":
            filters: dict = {}
            node = filters
            for _ in range(25):
                child: dict = {}
                node["nested"] = child
                node = child
        else:
            # A single oversized string slips past any per-array/depth bound but is caught by the byte cap.
            filters = {"metricName": "x" * (128 * 1024)}

        response = self.client.post(self.base_url, {"name": "Bad view", "filters": filters}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "filters"
