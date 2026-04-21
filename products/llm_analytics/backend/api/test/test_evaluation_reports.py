import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.llm_analytics.backend.models.evaluations import Evaluation


class TestEvaluationReportApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        self.base_url = f"/api/environments/{self.team.id}/llm_analytics/evaluation_reports/"

    def _create_report(self, **kwargs) -> EvaluationReport:
        defaults = {
            "team": self.team,
            "evaluation": self.evaluation,
            "frequency": EvaluationReport.Frequency.EVERY_N,
            "trigger_threshold": 100,
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return EvaluationReport.objects.create(**defaults)

    def _scheduled_payload(self, **overrides) -> dict:
        payload = {
            "evaluation": str(self.evaluation.id),
            "frequency": "scheduled",
            "rrule": "FREQ=DAILY",
            "starts_at": timezone.now().isoformat(),
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
        }
        payload.update(overrides)
        return payload

    def test_unauthenticated_user_cannot_access(self):
        self.client.logout()
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_reports(self):
        self._create_report(rrule="FREQ=DAILY", timezone_name="UTC")
        self._create_report()
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        # Default (non-MCP) list keeps the full payload the web UI relies on.
        first = results[0]
        for field in ("delivery_targets", "rrule", "starts_at", "timezone_name", "report_prompt_guidance"):
            self.assertIn(field, first)

    def test_mcp_list_returns_slim_payload(self):
        self._create_report(rrule="FREQ=DAILY", timezone_name="UTC")
        response = self.client.get(self.base_url, HTTP_X_POSTHOG_CLIENT="mcp")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        first = results[0]
        for dropped in (
            "rrule",
            "starts_at",
            "timezone_name",
            "delivery_targets",
            "max_sample_size",
            "report_prompt_guidance",
            "cooldown_minutes",
            "daily_run_cap",
            "created_by",
        ):
            self.assertNotIn(dropped, first)
        self.assertIn("id", first)
        self.assertIn("evaluation", first)

    def test_list_excludes_deleted(self):
        self._create_report()
        self._create_report(deleted=True)
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_create_scheduled_report(self):
        response = self.client.post(self.base_url, self._scheduled_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(EvaluationReport.objects.count(), 1)
        report = EvaluationReport.objects.first()
        assert report is not None
        self.assertEqual(report.team_id, self.team.id)
        self.assertEqual(report.created_by_id, self.user.id)
        self.assertEqual(report.rrule, "FREQ=DAILY")
        self.assertEqual(report.timezone_name, "UTC")

    def test_create_count_triggered_report_is_default(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "every_n",
                "trigger_threshold": 100,
                "delivery_targets": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        report = EvaluationReport.objects.first()
        assert report is not None
        self.assertTrue(report.is_count_triggered)
        self.assertEqual(report.rrule, "")
        self.assertIsNone(report.starts_at)

    def test_create_scheduled_sets_next_delivery_date(self):
        response = self.client.post(self.base_url, self._scheduled_payload(rrule="FREQ=HOURLY"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertIsNotNone(response.json()["next_delivery_date"])

    def test_create_allows_empty_delivery_targets(self):
        response = self.client.post(self.base_url, self._scheduled_payload(delivery_targets=[]), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_scheduled_requires_rrule(self):
        response = self.client.post(self.base_url, self._scheduled_payload(rrule=""), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "rrule")

    def test_create_scheduled_requires_starts_at(self):
        payload = self._scheduled_payload()
        payload.pop("starts_at")
        response = self.client.post(self.base_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "starts_at")

    def test_create_rejects_invalid_rrule(self):
        response = self.client.post(self.base_url, self._scheduled_payload(rrule="NOT_AN_RRULE"), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "rrule")

    def test_create_rejects_rrule_with_dtstart(self):
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(rrule="DTSTART:20260101T000000Z\nRRULE:FREQ=DAILY"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_without_frequency_enforces_trigger_threshold_max(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "trigger_threshold": EvaluationReport.TRIGGER_THRESHOLD_MAX + 1,
                "delivery_targets": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "trigger_threshold")

    def test_create_without_frequency_enforces_trigger_threshold_min(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "trigger_threshold": EvaluationReport.TRIGGER_THRESHOLD_MIN - 1,
                "delivery_targets": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "trigger_threshold")

    def test_validate_email_target(self):
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(delivery_targets=[{"type": "email"}]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_slack_target(self):
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(delivery_targets=[{"type": "slack"}]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_slack_target_valid(self):
        integration = Integration.objects.create(team=self.team, kind=Integration.IntegrationKind.SLACK, config={})
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(
                delivery_targets=[{"type": "slack", "integration_id": integration.id, "channel": "#reports"}]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

    def test_validate_slack_target_rejects_nonexistent_integration(self):
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(
                delivery_targets=[{"type": "slack", "integration_id": 999999, "channel": "#reports"}]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "delivery_targets")

    def test_validate_slack_target_rejects_cross_team_integration(self):
        # Integration belongs to a different team; must not be usable by this team.
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        foreign_integration = Integration.objects.create(
            team=other_team, kind=Integration.IntegrationKind.SLACK, config={}
        )
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(
                delivery_targets=[{"type": "slack", "integration_id": foreign_integration.id, "channel": "#reports"}]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "delivery_targets")

    def test_validate_slack_target_rejects_wrong_kind_integration(self):
        # Same team but not a Slack integration — reject so a github id can't masquerade.
        github_integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.GITHUB, config={}
        )
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(
                delivery_targets=[{"type": "slack", "integration_id": github_integration.id, "channel": "#reports"}]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("attr"), "delivery_targets")

    def test_validate_invalid_target_type(self):
        response = self.client.post(
            self.base_url,
            self._scheduled_payload(delivery_targets=[{"type": "webhook"}]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_report(self):
        report = self._create_report()
        response = self.client.get(f"{self.base_url}{report.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(report.id))

    def test_update_report(self):
        report = self._create_report()
        response = self.client.patch(
            f"{self.base_url}{report.id}/",
            {"frequency": "scheduled", "rrule": "FREQ=WEEKLY;BYDAY=MO", "starts_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        report.refresh_from_db()
        self.assertEqual(report.frequency, "scheduled")
        self.assertEqual(report.rrule, "FREQ=WEEKLY;BYDAY=MO")

    def test_delete_returns_405(self):
        report = self._create_report()
        response = self.client.delete(f"{self.base_url}{report.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_soft_delete_via_patch(self):
        report = self._create_report()
        response = self.client.patch(f"{self.base_url}{report.id}/", {"deleted": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.assertTrue(report.deleted)
        self.assertEqual(EvaluationReport.objects.filter(deleted=False).count(), 0)

    def test_runs_action_returns_paginated_shape(self):
        report = self._create_report()
        EvaluationReportRun.objects.create(
            report=report,
            content={},
            metadata={},
            period_start=timezone.now() - dt.timedelta(hours=1),
            period_end=timezone.now(),
        )
        response = self.client.get(f"{self.base_url}{report.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("results", body)
        self.assertIn("count", body)
        self.assertEqual(body["count"], 1)
        self.assertEqual(len(body["results"]), 1)

    # The /runs/ and /generate/ custom @actions have to declare required_scopes explicitly;
    # without them the default scope resolver returns None for non-CRUD action names and PAK
    # requests are rejected with "This action does not support Personal API Key access".
    @parameterized.expand(
        [
            ("read_scope_allowed", ["llm_analytics:read"], status.HTTP_200_OK),
            ("wrong_scope_denied", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_runs_action_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        report = self._create_report()
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.get(f"{self.base_url}{report.id}/runs/")
        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand(
        [
            ("write_scope_allowed", ["llm_analytics:write"], status.HTTP_202_ACCEPTED),
            ("wrong_scope_denied", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    @patch("products.llm_analytics.backend.api.evaluation_reports.async_to_sync")
    @patch("posthog.temporal.common.client.sync_connect")
    def test_generate_action_pak_scope(
        self,
        _name: str,
        scopes: list[str],
        expected_status: int,
        mock_sync_connect: MagicMock,
        mock_async_to_sync: MagicMock,
    ) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        report = self._create_report()
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.post(f"{self.base_url}{report.id}/generate/")
        self.assertEqual(response.status_code, expected_status)

    @patch("products.llm_analytics.backend.api.evaluation_reports.report_user_action")
    def test_create_reports_user_action(self, mock_report: MagicMock) -> None:
        response = self.client.post(self.base_url, self._scheduled_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        assert mock_report.called
        event_name = mock_report.call_args_list[0].args[1]
        self.assertEqual(event_name, "llma evaluation report created")

    @patch("products.llm_analytics.backend.api.evaluation_reports.report_user_action")
    def test_update_reports_user_action(self, mock_report: MagicMock) -> None:
        report = self._create_report()
        mock_report.reset_mock()
        response = self.client.patch(f"{self.base_url}{report.id}/", {"enabled": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert mock_report.called
        event_name = mock_report.call_args_list[0].args[1]
        self.assertEqual(event_name, "llma evaluation report updated")

    @patch("products.llm_analytics.backend.api.evaluation_reports.report_user_action")
    def test_soft_delete_reports_user_action(self, mock_report: MagicMock) -> None:
        report = self._create_report()
        mock_report.reset_mock()
        response = self.client.patch(f"{self.base_url}{report.id}/", {"deleted": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_name = mock_report.call_args_list[0].args[1]
        self.assertEqual(event_name, "llma evaluation report deleted")
