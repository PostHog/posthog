from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.team.team import Team

from products.logs.backend.alert_check_query import BucketedCount
from products.logs.backend.alerts_api import ALLOWED_WINDOW_MINUTES, MAX_ALERTS_PER_TEAM
from products.logs.backend.models import LogsAlertCheck, LogsAlertConfiguration


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

    @patch("products.logs.backend.alerts_api.report_user_action")
    def test_create(self, mock_report):
        data = self._create_via_api()
        assert data["name"] == "High error rate"
        assert data["threshold_count"] == 10
        assert data["state"] == "not_firing"
        assert data["enabled"] is True
        assert data["created_by"]["id"] == self.user.pk
        assert data["filters"] == {"severityLevels": ["error"]}

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs alert created"
        assert mock_report.call_args[0][2]["name"] == "High error rate"
        assert mock_report.call_args[0][2]["threshold_count"] == 10

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

    def test_last_error_message_null_when_no_errored_check(self):
        created = self._create_via_api()
        alert = LogsAlertConfiguration.objects.get(pk=created["id"])
        LogsAlertCheck.objects.create(
            alert=alert, threshold_breached=False, state_before="not_firing", state_after="not_firing"
        )

        response = self.client.get(f"{self.base_url}{created['id']}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["last_error_message"] is None

    def test_last_error_message_returns_most_recent_errored_check(self):
        created = self._create_via_api()
        alert = LogsAlertConfiguration.objects.get(pk=created["id"])
        LogsAlertCheck.objects.create(
            alert=alert,
            threshold_breached=False,
            state_before="not_firing",
            state_after="errored",
            error_message="Earlier timeout",
        )
        LogsAlertCheck.objects.create(
            alert=alert,
            threshold_breached=False,
            state_before="not_firing",
            state_after="errored",
            error_message="Latest ClickHouse timeout",
        )
        LogsAlertCheck.objects.create(
            alert=alert, threshold_breached=False, state_before="errored", state_after="not_firing"
        )

        response = self.client.get(f"{self.base_url}{created['id']}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["last_error_message"] == "Latest ClickHouse timeout"

    def test_update(self):
        created = self._create_via_api()

        response = self.client.put(
            f"{self.base_url}{created['id']}/",
            {**self._valid_payload(), "name": "Renamed"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed"

    @patch("products.logs.backend.alerts_api.report_user_action")
    def test_partial_update(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"name": "Patched"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Patched"

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs alert updated"
        assert mock_report.call_args[0][2]["name"] == "Patched"

    @patch("products.logs.backend.alerts_api.report_user_action")
    def test_delete(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not LogsAlertConfiguration.objects.filter(pk=created["id"]).exists()

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "logs alert deleted"
        assert mock_report.call_args[0][2]["name"] == "High error rate"

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

    # --- Edit behavior: recheck and state reset ---

    def test_threshold_change_resets_state_and_clears_next_check(self):
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(
            state="firing",
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
        )

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"threshold_count": 50},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["next_check_at"] is None

    def test_filter_change_resets_state(self):
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(state="firing")

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"filters": {"severityLevels": ["warn"]}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"

    def test_window_change_preserves_state_and_clears_next_check(self):
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(
            state="firing",
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
        )

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"window_minutes": 10},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "firing"
        assert response.json()["next_check_at"] is None

    def test_name_change_preserves_state_and_next_check(self):
        next_check = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(
            state="firing",
            next_check_at=next_check,
        )

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"name": "Renamed"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "firing"
        assert response.json()["next_check_at"] is not None

    # --- Snooze ---

    def test_snooze_sets_snoozed_state(self):
        created = self._create_via_api()
        snooze_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": snooze_time},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "snoozed"
        assert response.json()["snooze_until"] is not None

    def test_unsnooze_sets_not_firing_state(self):
        created = self._create_via_api()
        LogsAlertConfiguration.objects.filter(pk=created["id"]).update(
            state="snoozed",
            snooze_until=datetime.now(UTC) + timedelta(hours=1),
        )

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": None},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "not_firing"
        assert response.json()["snooze_until"] is None

    def test_snooze_rejects_past_datetime(self):
        created = self._create_via_api()
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": past_time},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_snooze_with_threshold_change_preserves_snoozed_state(self):
        created = self._create_via_api()
        snooze_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": snooze_time, "threshold_count": 100},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["state"] == "snoozed"
        assert data["snooze_until"] is not None
        assert data["threshold_count"] == 100

    def test_already_snoozed_threshold_change_preserves_snooze(self):
        created = self._create_via_api()
        snooze_time = datetime.now(UTC) + timedelta(hours=1)

        # First snooze the alert
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"snooze_until": snooze_time.isoformat()},
            format="json",
        )
        assert response.json()["state"] == "snoozed"

        # Now change threshold without touching snooze_until
        response = self.client.patch(
            f"{self.base_url}{created['id']}/",
            {"threshold_count": 200},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["state"] == "snoozed"
        assert data["snooze_until"] is not None
        assert data["threshold_count"] == 200

    # --- Destinations ---

    def _destinations_url(self, alert_id: str) -> str:
        return f"{self.base_url}{alert_id}/destinations/"

    def _destinations_delete_url(self, alert_id: str) -> str:
        return f"{self.base_url}{alert_id}/destinations/delete/"

    def _sync_destination_templates(self) -> None:
        # Destination creation goes through the full HogFunctionSerializer pipeline,
        # which looks up a HogFunctionTemplate by template_id. Seed Slack + webhook.
        from posthog.cdp.templates.hog_function_template import sync_template_to_db
        from posthog.cdp.templates.slack.template_slack import template as template_slack
        from posthog.models.hog_function_template import HogFunctionTemplate

        sync_template_to_db(template_slack)
        HogFunctionTemplate.objects.get_or_create(
            template_id="template-webhook",
            defaults={
                "sha": "1.0.0",
                "name": "Webhook",
                "description": "Generic webhook template",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "type": "destination",
                "status": "stable",
                "category": ["Integrations"],
                "free": True,
            },
        )

    @patch("products.logs.backend.alerts_api.report_user_action")
    def test_create_slack_destination_creates_one_hog_function_per_event_kind(self, mock_report):
        self._sync_destination_templates()
        from posthog.models.hog_functions.hog_function import HogFunction

        created = self._create_via_api()
        response = self.client.post(
            self._destinations_url(created["id"]),
            {
                "type": "slack",
                "slack_workspace_id": 42,
                "slack_channel_id": "C123",
                "slack_channel_name": "alerts",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        ids = response.json()["hog_function_ids"]
        assert len(ids) == 2  # firing + resolved

        hog_functions = HogFunction.objects.filter(id__in=ids).order_by("name")
        event_ids = sorted([(hf.filters or {})["events"][0]["id"] for hf in hog_functions])
        assert event_ids == ["$logs_alert_firing", "$logs_alert_resolved"]
        for hf in hog_functions:
            assert hf.template_id == "template-slack"
            inputs = hf.inputs or {}
            assert inputs["channel"]["value"] == "C123"
            assert inputs["slack_workspace"]["value"] == 42
            text_value = inputs["text"]["value"]
            assert "{if(" not in text_value
            alert_id_filter = (hf.filters or {})["properties"][0]
            assert alert_id_filter == {
                "key": "alert_id",
                "value": created["id"],
                "operator": "exact",
                "type": "event",
            }

        reset_calls = [c for c in mock_report.call_args_list if c.args[1] == "logs alert destination created"]
        assert len(reset_calls) == 1

    def test_create_webhook_destination_creates_one_hog_function_per_event_kind(self):
        from posthog.models.hog_functions.hog_function import HogFunction

        self._sync_destination_templates()
        created = self._create_via_api()
        response = self.client.post(
            self._destinations_url(created["id"]),
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        ids = response.json()["hog_function_ids"]
        assert len(ids) == 2

        hog_functions = HogFunction.objects.filter(id__in=ids)
        for hf in hog_functions:
            assert hf.template_id == "template-webhook"
            inputs = hf.inputs or {}
            assert inputs["url"]["value"] == "https://example.com/hook"
            body = inputs["body"]["value"]
            assert body["event"] in ("firing", "resolved")

    @parameterized.expand(
        [
            ("slack_missing_workspace", {"type": "slack", "slack_channel_id": "C1"}),
            ("slack_missing_channel", {"type": "slack", "slack_workspace_id": 1}),
            ("webhook_missing_url", {"type": "webhook"}),
            ("webhook_invalid_url", {"type": "webhook", "webhook_url": "not-a-url"}),
        ]
    )
    def test_create_destination_rejects_invalid_payloads(self, _name: str, payload: dict) -> None:
        created = self._create_via_api()
        response = self.client.post(self._destinations_url(created["id"]), payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_destination_on_other_teams_alert_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_alert = LogsAlertConfiguration.objects.create(
            team=other_team, name="Other", threshold_count=10, filters={"severityLevels": ["error"]}
        )
        response = self.client.post(
            self._destinations_url(str(other_alert.id)),
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_destination_removes_hog_functions(self):
        from posthog.models.hog_functions.hog_function import HogFunction

        self._sync_destination_templates()
        created = self._create_via_api()
        create_response = self.client.post(
            self._destinations_url(created["id"]),
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        ids = create_response.json()["hog_function_ids"]

        delete_response = self.client.post(
            self._destinations_delete_url(created["id"]),
            {"hog_function_ids": ids},
            format="json",
        )
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert HogFunction.objects.filter(id__in=ids, deleted=False).count() == 0

    def test_delete_destination_rejects_foreign_hog_function_ids(self):
        self._sync_destination_templates()
        created_a = self._create_via_api()
        created_b = self._create_via_api(name="Another alert")

        a_ids = self.client.post(
            self._destinations_url(created_a["id"]),
            {"type": "webhook", "webhook_url": "https://example.com/a"},
            format="json",
        ).json()["hog_function_ids"]
        b_ids = self.client.post(
            self._destinations_url(created_b["id"]),
            {"type": "webhook", "webhook_url": "https://example.com/b"},
            format="json",
        ).json()["hog_function_ids"]

        # Trying to delete alert A's HogFunctions via alert B's endpoint should fail.
        response = self.client.post(
            self._destinations_delete_url(created_b["id"]),
            {"hog_function_ids": a_ids + b_ids},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- Simulate ---

    def _simulate_url(self) -> str:
        return f"{self.base_url}simulate/"

    def _simulate_payload(self, **overrides) -> dict:
        defaults = {
            "filters": {"severityLevels": ["error"]},
            "threshold_count": 100,
            "threshold_operator": "above",
            "window_minutes": 5,
            "date_from": "-24h",
        }
        defaults.update(overrides)
        return defaults

    def _mock_minute_buckets(self, minute_counts: list[tuple[int, int]]) -> list[BucketedCount]:
        """Create 1-minute buckets. minute_counts is [(offset_minutes, count), ...]."""
        base = datetime(2025, 12, 16, 10, 0, tzinfo=UTC)
        return [BucketedCount(timestamp=base + timedelta(minutes=m), count=c) for m, c in minute_counts]

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_returns_response_shape(self, mock_query_cls):
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets([(0, 50), (1, 20)])

        response = self.client.post(self._simulate_url(), self._simulate_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "buckets" in data
        assert "fire_count" in data
        assert "resolve_count" in data
        assert "total_buckets" in data
        assert data["total_buckets"] > 0
        bucket = data["buckets"][0]
        assert "threshold_breached" in bucket
        assert "state" in bucket
        assert "notification" in bucket

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_fills_empty_minutes(self, mock_query_cls):
        # Two data points 10 minutes apart — should fill 1-min gaps between them
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets([(0, 50), (10, 200)])

        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(window_minutes=5),
            format="json",
        )
        data = response.json()
        # Should have many more buckets than 2 (filled 1-min gaps for the full range)
        assert data["total_buckets"] > 10

    @parameterized.expand(
        [
            (
                "fires",
                [(0, 40), (1, 40), (2, 40)],
                {"threshold_count": 100, "threshold_operator": "above", "window_minutes": 5},
                {"min_fire_count": 1},
            ),
            (
                "fires_and_resolves",
                [(0, 40), (1, 40), (2, 40)],
                {"threshold_count": 100, "threshold_operator": "above", "window_minutes": 5},
                {"min_fire_count": 1, "min_resolve_count": 1},
            ),
        ]
    )
    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_rolling_window(self, _name, buckets, payload_overrides, expected, mock_query_cls):
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets(buckets)

        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(**payload_overrides),
            format="json",
        )
        data = response.json()
        if "min_fire_count" in expected:
            assert data["fire_count"] >= expected["min_fire_count"]
        if "min_resolve_count" in expected:
            assert data["resolve_count"] >= expected["min_resolve_count"]

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_n_of_m_delays_firing(self, mock_query_cls):
        # window=1 (so rolling sum = per-minute count), 2-of-3 N-of-M
        # Minutes: 150, 50, 150 — at minute 2, breach_count in window of 3 = 2 >= 2 -> fires
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets(
            [(0, 150), (1, 50), (2, 150)]
        )

        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(
                threshold_count=100,
                threshold_operator="above",
                evaluation_periods=3,
                datapoints_to_alarm=2,
                window_minutes=1,
            ),
            format="json",
        )
        data = response.json()
        data_buckets = [b for b in data["buckets"] if b["count"] > 0]
        # Minute 0: 150 breached, but only 1-of-1 so far -> not_firing
        assert data_buckets[0]["state"] == "not_firing"
        # Minute 2: 150 breached, now 2-of-3 -> firing
        assert data_buckets[2]["state"] == "firing"
        assert data_buckets[2]["notification"] == "fire"

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_cooldown_suppresses_renotification(self, mock_query_cls):
        # window=1, cooldown=5 min. Fires at minute 1, should suppress re-fire at minute 3.
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets(
            [(0, 50), (1, 150), (2, 50), (3, 150), (4, 50)]
        )

        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(
                threshold_count=100,
                threshold_operator="above",
                cooldown_minutes=5,
                window_minutes=1,
            ),
            format="json",
        )
        data = response.json()
        data_buckets = [b for b in data["buckets"] if b["count"] > 0]
        # Minute 1: fires
        assert data_buckets[1]["notification"] == "fire"
        # Minute 3: would fire again, cooldown suppresses
        assert data_buckets[3]["state"] == "firing"
        assert data_buckets[3]["notification"] == "none"
        assert data["fire_count"] == 1

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_empty_results(self, mock_query_cls):
        mock_query_cls.return_value.execute_bucketed.return_value = []

        response = self.client.post(self._simulate_url(), self._simulate_payload(), format="json")
        data = response.json()
        assert data["fire_count"] == 0
        assert data["resolve_count"] == 0
        for b in data["buckets"]:
            assert b["count"] == 0

    def test_simulate_rejects_empty_filters(self):
        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(filters={}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_simulate_rejects_invalid_window(self):
        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(window_minutes=7),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_simulate_rejects_n_greater_than_m(self):
        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(evaluation_periods=2, datapoints_to_alarm=3),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @freeze_time("2025-12-16T10:30:00Z")
    @patch("products.logs.backend.alerts_api.AlertCheckQuery")
    def test_simulate_echoes_threshold_config(self, mock_query_cls):
        mock_query_cls.return_value.execute_bucketed.return_value = self._mock_minute_buckets([(0, 10)])

        response = self.client.post(
            self._simulate_url(),
            self._simulate_payload(threshold_count=42, threshold_operator="below"),
            format="json",
        )
        data = response.json()
        assert data["threshold_count"] == 42
        assert data["threshold_operator"] == "below"
