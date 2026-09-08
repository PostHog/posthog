from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from posthog.models import Organization, Team

REPORT_MODULE = "products.posthog_ai.backend.services.usage.report"


class TestAIUsageAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The report is cached per team, so one test must not serve the next one's answer.
        cache.clear()
        self.organization.usage = {"period": ["2026-05-02T14:51:12Z", "2026-06-02T14:51:12Z"]}
        self.organization.save()

    def _get(self, query: str = ""):
        with (
            patch(f"{REPORT_MODULE}.get_ai_credits_for_team", return_value=800),
            patch(f"{REPORT_MODULE}.get_ai_credits_for_conversation", return_value=12),
            patch(f"{REPORT_MODULE}.get_ai_free_tier_credits", return_value=2000),
            patch(f"{REPORT_MODULE}.get_ai_credits", return_value=250),
        ):
            return self.client.get(f"/api/projects/{self.team.id}/ai_usage/{query}")

    def test_reports_conversation_product_and_team_credits(self):
        response = self._get(f"?conversation_id={uuid4()}&product=slack_app")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["conversation_credits"], 12)
        self.assertEqual(body["period_credits"], 800)
        self.assertEqual(body["remaining_credits"], 1200)
        self.assertEqual(body["product"], {"name": "Slack app", "credits": 250, "separate_bucket": False})
        self.assertIn("**Slack app this billing period**: 250 credits", body["message"])

    def test_rejects_a_conversation_id_that_is_not_a_uuid(self):
        response = self._get("?conversation_id=not-a-uuid")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_read_another_organizations_project(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.get(f"/api/projects/{other_team.id}/ai_usage/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
