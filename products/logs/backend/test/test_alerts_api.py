from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.team.team import Team

from products.logs.backend.alerts_api import ALLOWED_WINDOW_MINUTES, MAX_ALERTS_PER_TEAM
from products.logs.backend.models import LogsAlertConfiguration


class TestLogsAlertAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/alerts/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _valid_payload(self, **overrides) -> dict:
        defaults = {
            "name": "High error rate",
            "threshold_count": 10,
            "filters": {"severityLevels": ["error"]},
        }
        defaults.update(overrides)
        return defaults

    def _create_via_api(self, **overrides) -> dict:
        response = self.client.post(self.base_url, self._valid_payload(**overrides), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    # --- CRUD ---

    def test_create(self):
        data = self._create_via_api()
        assert data["name"] == "High error rate"
        assert data["threshold_count"] == 10
        assert data["state"] == "not_firing"
        assert data["enabled"] is True
        assert data["created_by"]["id"] == self.user.pk
        assert data["filters"] == {"severityLevels": ["error"]}

    def test_list(self):
        self._create_via_api(name="Alert 1")
        self._create_via_api(name="Alert 2")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert results[0]["name"] == "Alert 2"
        assert results[1]["name"] == "Alert 1"

    def test_retrieve(self):
        created = self._create_via_api()

        response = self.client.get(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == created["id"]

    def test_update(self):
        created = self._create_via_api()

        response = self.client.put(
            f"{self.base_url}{created['id']}/",
            {**self._valid_payload(), "name": "Renamed"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed"

    def test_partial_update(self):
        created = self._create_via_api()

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"name": "Patched"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Patched"

    def test_delete(self):
        created = self._create_via_api()

        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not LogsAlertConfiguration.objects.filter(pk=created["id"]).exists()

    # --- Team isolation ---

    def test_list_only_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        LogsAlertConfiguration.objects.create(
            team=team2,
            name="Other team alert",
            threshold_count=5,
            created_by=self.user,
            filters={"severityLevels": ["warn"]},
        )
        self._create_via_api(name="My alert")

        response = self.client.get(self.base_url)
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "My alert"

    def test_cannot_retrieve_other_teams_alert(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_alert = LogsAlertConfiguration.objects.create(
            team=team2,
            name="Other",
            threshold_count=5,
            created_by=self.user,
            filters={"severityLevels": ["error"]},
        )

        response = self.client.get(f"{self.base_url}{other_alert.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_teams_alert(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_alert = LogsAlertConfiguration.objects.create(
            team=team2,
            name="Other",
            threshold_count=5,
            created_by=self.user,
            filters={"severityLevels": ["error"]},
        )

        response = self.client.delete(f"{self.base_url}{other_alert.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert LogsAlertConfiguration.objects.filter(pk=other_alert.id).exists()

    def test_unauthorized_access(self):
        client = APIClient()
        response = client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # --- Validation: filters ---

    def test_create_rejects_empty_filters(self):
        response = self.client.post(
            self.base_url,
            self._valid_payload(filters={}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "filters"

    @parameterized.expand(
        [
            ("list", []),
            ("string", "error"),
            ("number", 42),
            ("null", None),
        ]
    )
    def test_create_rejects_non_dict_filters(self, _name, filters):
        response = self.client.post(
            self.base_url,
            self._valid_payload(filters=filters),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "filters"

    @parameterized.expand(
        [
            ("severity_levels", {"severityLevels": ["error"]}),
            ("service_names", {"serviceNames": ["my-service"]}),
            ("filter_group", {"filterGroup": {"type": "AND", "values": []}}),
        ]
    )
    def test_create_accepts_valid_filter(self, _name, filters):
        response = self.client.post(
            self.base_url,
            self._valid_payload(filters=filters),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    # --- Validation: window ---

    @parameterized.expand([(w,) for w in sorted(ALLOWED_WINDOW_MINUTES)])
    def test_create_accepts_valid_window(self, window):
        response = self.client.post(
            self.base_url,
            self._valid_payload(window_minutes=window),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    @parameterized.expand([(2,), (7,), (45,), (120,)])
    def test_create_rejects_invalid_window(self, window):
        response = self.client.post(
            self.base_url,
            self._valid_payload(window_minutes=window),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "window_minutes"

    # --- Validation: N-of-M ---

    def test_create_rejects_n_greater_than_m(self):
        response = self.client.post(
            self.base_url,
            self._valid_payload(datapoints_to_alarm=3, evaluation_periods=2),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "datapoints_to_alarm"

    def test_create_accepts_valid_n_of_m(self):
        response = self.client.post(
            self.base_url,
            self._valid_payload(datapoints_to_alarm=2, evaluation_periods=3),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    # --- Per-team limit ---

    def test_per_team_limit(self):
        for i in range(MAX_ALERTS_PER_TEAM):
            LogsAlertConfiguration.objects.create(
                team=self.team,
                name=f"Alert {i}",
                threshold_count=1,
                created_by=self.user,
                filters={"severityLevels": ["error"]},
            )

        response = self.client.post(
            self.base_url,
            self._valid_payload(name="One too many"),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum" in str(response.json())

    # --- Read-only fields ---

    def test_state_ignored_on_create(self):
        data = self._create_via_api(state="firing")
        assert data["state"] == "not_firing"

    def test_state_ignored_on_update(self):
        created = self._create_via_api()
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"state": "firing"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"

    # --- Defaults ---

    def test_create_with_minimal_fields(self):
        data = self._create_via_api()
        assert data["enabled"] is True
        assert data["threshold_operator"] == "above"
        assert data["window_minutes"] == 5
        assert data["check_interval_minutes"] == 1
        assert data["evaluation_periods"] == 1
        assert data["datapoints_to_alarm"] == 1
        assert data["cooldown_minutes"] == 0
        assert data["consecutive_failures"] == 0

    # --- Partial update preserves existing filters ---

    def test_partial_update_non_filter_field(self):
        created = self._create_via_api(filters={"severityLevels": ["error"]})

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"name": "Just rename"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Just rename"
        assert response.json()["filters"] == {"severityLevels": ["error"]}

    # --- Environments URL ---

    def test_environments_url(self):
        created = self._create_via_api()
        env_url = f"/api/environments/{self.team.pk}/logs/alerts/"

        response = self.client.get(env_url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

        response = self.client.get(f"{env_url}{created['id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == created["id"]

    # --- Disable resets state ---

    def test_disable_resets_firing_state(self):
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(state="firing")

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["enabled"] is False
