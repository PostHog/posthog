from datetime import UTC, datetime
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.types import FeatureFlagResult

from posthog.models import Organization, User

from products.tasks.backend.access import PostHogAIAccessDecision, get_posthog_ai_access_decision

from ee.billing.billing_manager import OrganizationFundingStatus, PrepaidCreditState

RULES = {"cutoff_date": "2026-06-01T00:00:00+00:00", "min_trust_score": 5}


class TestPostHogAIAccessDecision(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "sandbox_flag_beats_every_deny",
                {"phai-sandbox-mode"},
                False,
                RULES,
                "Startup",
                True,
                0,
                "2026-09-01",
                PostHogAIAccessDecision.GRANDFATHERED,
            ),
            (
                "tasks_flag_beats_every_deny",
                {"tasks"},
                True,
                RULES,
                None,
                True,
                0,
                "2026-09-01",
                PostHogAIAccessDecision.GRANDFATHERED,
            ),
            (
                "beta_off_denies_outside_override",
                set(),
                False,
                RULES,
                None,
                False,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.BETA_OFF,
            ),
            (
                "startup_program",
                set(),
                True,
                RULES,
                "YC",
                False,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.STARTUP_PROGRAM,
            ),
            (
                "prepaid_credits",
                set(),
                True,
                RULES,
                None,
                True,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.PREPAID_CREDITS,
            ),
            (
                "created_after_cutoff",
                set(),
                True,
                RULES,
                None,
                False,
                9,
                "2026-06-01",
                PostHogAIAccessDecision.CREATED_AFTER_CUTOFF,
            ),
            ("low_trust", set(), True, RULES, None, False, 4, "2025-01-01", PostHogAIAccessDecision.LOW_TRUST),
            ("passes_every_rule", set(), True, RULES, None, False, 5, "2025-01-01", PostHogAIAccessDecision.ALLOWED),
            (
                "beta_without_rules_fails_closed",
                set(),
                True,
                None,
                None,
                False,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.UNRESOLVED,
            ),
        ]
    )
    def test_decision(
        self,
        _name: str,
        grandfathered_flags: set[str],
        beta_enabled: bool,
        rules: dict[str, Any] | None,
        startup_program_label: str | None,
        has_prepaid_credits: bool,
        trust_score: int,
        org_created: str,
        expected: PostHogAIAccessDecision,
    ) -> None:
        organization = Organization(
            name="Fixture org",
            created_at=datetime.fromisoformat(org_created).replace(tzinfo=UTC),
            customer_trust_scores={"events": trust_score},
        )
        user = User(email="fixture@example.com", distinct_id="fixture-distinct-id")
        prepaid = PrepaidCreditState.ACTIVE if has_prepaid_credits else PrepaidCreditState.NONE
        beta = FeatureFlagResult(key="phai-2-beta", enabled=beta_enabled, variant=None, payload=rules, reason=None)

        with (
            patch(
                "products.tasks.backend.access.get_feature_flag_or_none",
                side_effect=lambda key, *_args, **_kwargs: key in grandfathered_flags,
            ),
            patch("products.tasks.backend.access.posthoganalytics.get_feature_flag_result", return_value=beta),
            patch(
                "products.tasks.backend.access._get_funding_status",
                return_value=OrganizationFundingStatus(
                    startup_program_label=startup_program_label, prepaid_credit_state=prepaid
                ),
            ),
        ):
            decision = get_posthog_ai_access_decision(user, organization)

        self.assertEqual(decision, expected)
