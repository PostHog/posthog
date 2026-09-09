from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from products.posthog_ai.backend.services.usage.report import build_usage_report

MODULE = "products.posthog_ai.backend.services.usage.report"

BILLING_PERIOD = ["2026-05-02T14:51:12Z", "2026-06-02T14:51:12Z"]


class TestUsageReport(BaseTest):
    def setUp(self):
        super().setUp()
        # The report is cached per team, so one test must not serve the next one's answer.
        cache.clear()
        self.organization.usage = {
            "period": BILLING_PERIOD,
            "posthog_code_credits": {"usage": 4000, "todays_usage": 300, "limit": 10000},
        }
        self.organization.save()

    def _build(self, **kwargs):
        with (
            patch(f"{MODULE}.get_ai_credits_for_team", return_value=800),
            patch(f"{MODULE}.get_ai_credits_for_conversation", return_value=12) as conversation_credits,
            patch(f"{MODULE}.get_ai_free_tier_credits", return_value=2000),
            patch(f"{MODULE}.get_ai_credits", return_value=250) as product_credits,
        ):
            report = build_usage_report(self.team, **kwargs)
        return report, product_credits, conversation_credits

    def test_reports_a_products_own_credits_from_its_events(self):
        report, product_credits, _ = self._build(product="slack_app")

        assert report.product is not None
        self.assertEqual(report.product.label, "Slack app")
        self.assertEqual(report.product.credits, 250)
        self.assertFalse(report.product.separate_bucket)
        self.assertEqual(product_credits.call_args.kwargs["ai_products"], ["slack_app"])

    def test_reports_desktop_credits_from_billing_rather_than_events(self):
        # Desktop generations are only readable from the US, so summing events would report 0 on EU.
        # Billing is region-independent, and posthog_code is the whole of its own bucket.
        report, product_credits, _ = self._build(product="posthog_code")

        assert report.product is not None
        self.assertEqual(report.product.label, "PostHog Desktop")
        self.assertEqual(report.product.credits, 4300)
        self.assertTrue(report.product.separate_bucket)
        product_credits.assert_not_called()

    @parameterized.expand(
        [
            # An internal surface with no credit counter of its own.
            ("no_counter", "background_agents", {"period": BILLING_PERIOD}),
            # Billing has never synced the bucket, which is unknown spend rather than none.
            ("bucket_unsynced", "posthog_code", {"period": BILLING_PERIOD}),
        ]
    )
    def test_omits_the_product_row(self, _name: str, product: str, usage: dict):
        self.organization.usage = usage
        self.organization.save()

        report, _, _ = self._build(product=product)

        self.assertIsNone(report.product)

    def test_omits_the_conversation_row_when_no_conversation_is_in_scope(self):
        report, _, conversation_credits = self._build(product="slack_app")

        self.assertIsNone(report.conversation_credits)
        conversation_credits.assert_not_called()
        self.assertNotIn("Current conversation", report.message)

    def test_counts_a_conversation_from_its_own_start(self):
        started_at = datetime(2026, 5, 3, 9, 0, tzinfo=UTC)
        conversation_id = uuid4()

        report, _, conversation_credits = self._build(
            conversation_id=conversation_id, conversation_started_at=started_at
        )

        self.assertEqual(report.conversation_credits, 12)
        self.assertEqual(conversation_credits.call_args.kwargs["begin"], started_at)
        self.assertEqual(conversation_credits.call_args.kwargs["conversation_id"], conversation_id)
        self.assertIn("**Current conversation**: 12 credits", report.message)

    def test_serves_a_repeated_ask_without_querying_again(self):
        # Every miss costs up to three ClickHouse scans over the whole billing period.
        self._build(product="slack_app")
        _, product_credits, _ = self._build(product="slack_app")

        product_credits.assert_not_called()

    def test_reports_the_teams_billing_period(self):
        report, _, _ = self._build()

        self.assertEqual(report.usage_period.label, "Billing period")
        self.assertEqual(report.period_credits, 800)
        self.assertEqual(report.remaining_credits, 1200)
