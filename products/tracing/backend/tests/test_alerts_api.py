from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.tracing.backend.models import TracingAlertConfiguration, TracingAlertEvent
from products.tracing.backend.presentation.views_alerts_api import ALLOWED_WINDOW_MINUTES, MAX_ALERTS_PER_TEAM


class TestTracingAlertAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/tracing/alerts/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)
        scope = team_scope(self.team.id, canonical=True)
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)

    def _valid_payload(self, **overrides) -> dict:
        defaults = {"name": "High error rate", "threshold_count": 10, "filters": {"serviceNames": ["web"]}}
        defaults.update(overrides)
        return defaults

    def _create_via_api(self, **overrides) -> dict:
        response = self.client.post(self.base_url, self._valid_payload(**overrides), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    # --- CRUD ---

    @patch("products.tracing.backend.presentation.views_alerts_api.report_user_action")
    def test_create(self, mock_report):
        data = self._create_via_api()
        assert data["name"] == "High error rate"
        assert data["threshold_count"] == 10
        assert data["state"] == "not_firing"
        assert data["alert_type"] == "threshold"
        assert data["enabled"] is True
        assert data["first_enabled_at"] is not None
        assert data["created_by"]["id"] == self.user.pk
        assert data["filters"] == {"serviceNames": ["web"]}

        mock_report.assert_called_once()
        assert mock_report.call_args.args[1] == "tracing alert created"

    @freeze_time("2026-01-01T23:00:00Z")
    def test_create_with_quiet_hours_defers_next_check(self):
        data = self._create_via_api(schedule_restriction={"blocked_windows": [{"start": "22:00", "end": "07:00"}]})

        assert data["schedule_restriction"] == {"blocked_windows": [{"start": "22:00", "end": "07:00"}]}
        assert data["next_check_at"] == "2026-01-02T07:00:00Z"

    def test_create_with_snooze_until_sets_snoozed_state(self):
        data = self._create_via_api(snooze_until="2099-01-01T00:00:00Z")
        assert data["state"] == "snoozed"
        assert data["snooze_until"] == "2099-01-01T00:00:00Z"

    def test_create_rejects_empty_filters(self):
        response = self.client.post(self.base_url, self._valid_payload(filters={}), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_disabled_with_empty_filters_succeeds(self):
        response = self.client.post(self.base_url, self._valid_payload(enabled=False, filters={}), format="json")
        assert response.status_code == status.HTTP_201_CREATED

    @parameterized.expand([(w,) for w in sorted(ALLOWED_WINDOW_MINUTES)])
    def test_create_accepts_valid_window(self, window):
        response = self.client.post(self.base_url, self._valid_payload(window_minutes=window), format="json")
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_rejects_invalid_window(self):
        response = self.client.post(self.base_url, self._valid_payload(window_minutes=7), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_rejects_n_greater_than_m(self):
        response = self.client.post(
            self.base_url,
            self._valid_payload(evaluation_periods=2, datapoints_to_alarm=3),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrieve(self):
        created = self._create_via_api()
        response = self.client.get(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == created["id"]

    def test_list(self):
        self._create_via_api(name="Alert 1")
        self._create_via_api(name="Alert 2")
        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

    def test_update(self):
        created = self._create_via_api()
        response = self.client.patch(f"{self.base_url}{created['id']}/", {"name": "Renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed"

    @patch("products.tracing.backend.presentation.views_alerts_api.report_user_action")
    def test_delete(self, mock_report):
        created = self._create_via_api()
        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert TracingAlertConfiguration.objects.unscoped().filter(id=created["id"]).count() == 0

    # --- Read-only fields ---

    def test_state_ignored_on_create(self):
        data = self._create_via_api(state="firing")
        assert data["state"] == "not_firing"

    def test_state_ignored_on_update(self):
        created = self._create_via_api()
        response = self.client.patch(f"{self.base_url}{created['id']}/", {"state": "firing"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"

    # --- Team isolation ---

    def test_list_only_own_team(self):
        self._create_via_api()
        other_team = self.organization.teams.create(name="Other team")
        with team_scope(other_team.id, canonical=True):
            TracingAlertConfiguration.objects.create(team=other_team, name="Other", threshold_count=1)

        response = self.client.get(self.base_url)
        assert len(response.json()["results"]) == 1

    def test_cannot_retrieve_other_teams_alert(self):
        other_team = self.organization.teams.create(name="Other team")
        with team_scope(other_team.id, canonical=True):
            other_alert = TracingAlertConfiguration.objects.create(team=other_team, name="Other", threshold_count=1)

        response = self.client.get(f"{self.base_url}{other_alert.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- Per-team limit ---

    def test_per_team_limit(self):
        for i in range(MAX_ALERTS_PER_TEAM):
            self._create_via_api(name=f"Alert {i}")

        response = self.client.post(self.base_url, self._valid_payload(name="Boundary"), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TracingAlertConfiguration.objects.for_team(self.team.id, canonical=True).count() == MAX_ALERTS_PER_TEAM

    # --- Control-plane transitions via PATCH ---

    def test_disable_resets_firing_state(self):
        created = self._create_via_api()
        TracingAlertConfiguration.objects.filter(pk=created["id"]).update(state="firing")

        response = self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": False}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["enabled"] is False

    def test_snooze_sets_snoozed_state(self):
        created = self._create_via_api()
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": "2099-01-01T00:00:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "snoozed"

    def test_unsnooze_sets_not_firing_state(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['id']}/", {"snooze_until": "2099-01-01T00:00:00Z"}, format="json")

        response = self.client.patch(f"{self.base_url}{created['id']}/", {"snooze_until": None}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"

    def test_enable_with_snooze_until_sets_snoozed_not_not_firing(self):
        created = self._create_via_api(enabled=False)
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"enabled": True, "snooze_until": "2099-01-01T00:00:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "snoozed"

    def test_snooze_rejects_past_datetime(self):
        created = self._create_via_api()
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": "2020-01-01T00:00:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_threshold_change_resets_state_and_clears_next_check(self):
        created = self._create_via_api()
        TracingAlertConfiguration.objects.filter(pk=created["id"]).update(
            state="firing", next_check_at=datetime(2099, 1, 1, tzinfo=UTC)
        )

        response = self.client.patch(f"{self.base_url}{created['id']}/", {"threshold_count": 50}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["next_check_at"] is None

    def test_update_writes_control_plane_event_row(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": False}, format="json")

        event = TracingAlertEvent.objects.get(alert_id=created["id"], kind=TracingAlertEvent.Kind.DISABLE)
        assert event.state_before == "not_firing"
        assert event.state_after == "not_firing"

    # --- events action ---

    def test_events_returns_rows_newest_first(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": False}, format="json")
        self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": True}, format="json")

        response = self.client.get(f"{self.base_url}{created['id']}/events/")
        assert response.status_code == status.HTTP_200_OK
        kinds = [e["kind"] for e in response.json()["results"]]
        assert kinds == ["enable", "disable"]

    def test_events_filter_by_kind(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": False}, format="json")

        response = self.client.get(f"{self.base_url}{created['id']}/events/?kind=disable")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    def test_events_rejects_unknown_kind(self):
        created = self._create_via_api()
        response = self.client.get(f"{self.base_url}{created['id']}/events/?kind=bogus")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_events_scoped_to_alert_team(self):
        created = self._create_via_api()
        other_team = self.organization.teams.create(name="Other team")
        with team_scope(other_team.id, canonical=True):
            other_alert = TracingAlertConfiguration.objects.create(team=other_team, name="Other", threshold_count=1)

        response = self.client.get(f"{self.base_url}{other_alert.id}/events/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response = self.client.get(f"{self.base_url}{created['id']}/events/")
        assert response.status_code == status.HTTP_200_OK

    # --- reset action ---

    def test_reset_broken_alert(self):
        created = self._create_via_api()
        TracingAlertConfiguration.objects.filter(pk=created["id"]).update(state="broken", consecutive_failures=5)

        response = self.client.post(f"{self.base_url}{created['id']}/reset/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["consecutive_failures"] == 0

    @parameterized.expand(
        [
            ("not_firing", "not_firing"),
            ("firing", "firing"),
            ("snoozed", "snoozed"),
        ]
    )
    def test_reset_rejects_non_broken_alert(self, _name, state):
        created = self._create_via_api()
        TracingAlertConfiguration.objects.filter(pk=created["id"]).update(state=state)

        response = self.client.post(f"{self.base_url}{created['id']}/reset/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_reset_other_teams_alert_returns_404(self):
        other_team = self.organization.teams.create(name="Other team")
        with team_scope(other_team.id, canonical=True):
            other_alert = TracingAlertConfiguration.objects.create(
                team=other_team, name="Other", threshold_count=1, state="broken"
            )

        response = self.client.post(f"{self.base_url}{other_alert.id}/reset/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- state_timeline ---

    def test_state_timeline_single_interval_for_empty_alert(self):
        created = self._create_via_api()
        timeline = created["state_timeline"]
        assert len(timeline) == 1
        assert timeline[0]["state"] == "not_firing"
        assert timeline[0]["enabled"] is True

    def test_state_timeline_tracks_enable_disable_toggles(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['id']}/", {"enabled": False}, format="json")

        response = self.client.get(f"{self.base_url}{created['id']}/")
        timeline = response.json()["state_timeline"]
        assert timeline[-1]["enabled"] is False

    # --- Feature flag gating ---

    def test_requires_feature_flag(self):
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
