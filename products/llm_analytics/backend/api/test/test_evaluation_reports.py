import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from rest_framework import status

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
            "frequency": "daily",
            "start_date": timezone.now(),
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return EvaluationReport.objects.create(**defaults)

    def test_unauthenticated_user_cannot_access(self):
        self.client.logout()
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_reports(self):
        self._create_report()
        self._create_report()
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_excludes_deleted(self):
        self._create_report()
        self._create_report(deleted=True)
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_create_report(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "email", "value": "test@example.com"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(EvaluationReport.objects.count(), 1)
        report = EvaluationReport.objects.first()
        self.assertEqual(report.team_id, self.team.id)
        self.assertEqual(report.created_by_id, self.user.id)

    def test_create_report_sets_next_delivery_date(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "hourly",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "email", "value": "test@example.com"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.json()["next_delivery_date"])

    def test_create_requires_delivery_targets(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_email_target(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "email"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_slack_target(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "slack"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_slack_target_valid(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "slack", "integration_id": 1, "channel": "#reports"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_validate_invalid_target_type(self):
        response = self.client.post(
            self.base_url,
            {
                "evaluation": str(self.evaluation.id),
                "frequency": "daily",
                "start_date": timezone.now().isoformat(),
                "delivery_targets": [{"type": "webhook"}],
            },
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
            {"frequency": "weekly"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.assertEqual(report.frequency, "weekly")

    def test_delete_report_soft_deletes(self):
        report = self._create_report()
        response = self.client.delete(f"{self.base_url}{report.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        report.refresh_from_db()
        self.assertTrue(report.deleted)
        self.assertEqual(EvaluationReport.objects.filter(deleted=False).count(), 0)

    def test_runs_action(self):
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
        self.assertEqual(len(response.json()), 1)

    @patch("posthog.temporal.common.client.sync_connect")
    def test_generate_action(self, mock_connect):
        report = self._create_report()
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()
        mock_connect.return_value = mock_client

        response = self.client.post(f"{self.base_url}{report.id}/generate/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_client.start_workflow.assert_called_once()

    @patch("posthog.temporal.common.client.sync_connect")
    def test_generate_action_handles_failure(self, mock_connect):
        report = self._create_report()
        mock_connect.side_effect = Exception("temporal down")

        response = self.client.post(f"{self.base_url}{report.id}/generate/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
