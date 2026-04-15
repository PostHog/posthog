from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.team.team import Team

from products.logs.backend.models import LogsView


class TestLogsViewAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/environments/{self.team.pk}/logs/views/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _valid_payload(self, **overrides) -> dict:
        defaults = {
            "name": "Error logs",
            "filters": {"severityLevels": ["error", "fatal"]},
        }
        defaults.update(overrides)
        return defaults

    def _create_via_api(self, **overrides) -> dict:
        response = self.client.post(self.base_url, self._valid_payload(**overrides), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    # --- CRUD ---

    @patch("products.logs.backend.views_api.report_user_action")
    def test_create(self, mock_report):
        data = self._create_via_api()
        assert data["name"] == "Error logs"
        assert data["filters"] == {"severityLevels": ["error", "fatal"]}
        assert data["pinned"] is False
        assert data["short_id"] is not None
        assert data["created_by"]["id"] == self.user.pk

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs view created"
        assert mock_report.call_args[0][2]["name"] == "Error logs"
        assert mock_report.call_args[0][2]["has_filters"] is True

    def test_list(self):
        self._create_via_api(name="View 1")
        self._create_via_api(name="View 2")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert {r["name"] for r in results} == {"View 1", "View 2"}

    def test_retrieve(self):
        created = self._create_via_api()

        response = self.client.get(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == created["short_id"]
        assert response.json()["name"] == "Error logs"

    @patch("products.logs.backend.views_api.report_user_action")
    def test_partial_update(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Renamed view"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed view"

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs view updated"
        assert mock_report.call_args[0][2]["name"] == "Renamed view"

    def test_partial_update_preserves_filters(self):
        created = self._create_via_api(filters={"severityLevels": ["error"], "serviceNames": ["api"]})

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Just rename"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Just rename"
        assert response.json()["filters"] == {"severityLevels": ["error"], "serviceNames": ["api"]}

    @patch("products.logs.backend.views_api.report_user_action")
    def test_delete(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.delete(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not LogsView.objects.filter(pk=created["id"]).exists()

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs view deleted"
        assert mock_report.call_args[0][2]["name"] == "Error logs"

    # --- Filters are optional ---

    def test_create_with_empty_filters(self):
        data = self._create_via_api(filters={})
        assert data["filters"] == {}

    def test_create_with_no_filters(self):
        response = self.client.post(self.base_url, {"name": "Minimal view"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["filters"] == {}

    def test_create_with_complex_filters(self):
        filters = {
            "severityLevels": ["error"],
            "serviceNames": ["api", "worker"],
            "searchTerm": "timeout",
            "filterGroup": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "env", "value": "production", "type": "log_entry", "operator": "exact"}],
                    }
                ],
            },
        }
        data = self._create_via_api(filters=filters)
        assert data["filters"] == filters

    # --- Validation ---

    @parameterized.expand(
        [
            ("missing_name", {"filters": {}}),
            ("blank_name", {"name": "", "filters": {}}),
        ]
    )
    def test_create_rejects_invalid_name(self, _label, payload):
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- Cross-team update isolation ---

    def test_cannot_update_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = LogsView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.patch(
            f"{self.base_url}{other_view.short_id}/",
            {"name": "Hacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_view.refresh_from_db()
        assert other_view.name == "Other"

    # --- Read-only fields ---

    def test_short_id_ignored_on_create(self):
        data = self._create_via_api(short_id="custom123")
        assert data["short_id"] != "custom123"

    def test_short_id_ignored_on_update(self):
        created = self._create_via_api()
        original_short_id = created["short_id"]

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"short_id": "changed"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == original_short_id

    # --- Team isolation ---

    def test_list_only_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        LogsView.objects.create(team=team2, name="Other team view", created_by=self.user)
        self._create_via_api(name="My view")

        response = self.client.get(self.base_url)
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "My view"

    def test_cannot_retrieve_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = LogsView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.get(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = LogsView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.delete(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert LogsView.objects.filter(pk=other_view.id).exists()

    # --- Auth ---

    def test_unauthorized_access(self):
        client = APIClient()
        response = client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # --- Feature flag ---

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_returns_403_when_feature_flag_disabled(self, _mock_feature_enabled):
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    # --- Pinned ---

    def test_pin_view(self):
        created = self._create_via_api()

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"pinned": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["pinned"] is True
