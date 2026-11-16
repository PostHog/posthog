import json
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.types import FeatureFlagResult

from posthog.models import Organization, User

from products.tasks.backend.access import (
    DesktopAccessResolutionError,
    PostHogAIAccessDecision,
    get_cached_posthog_ai_access_decision,
    get_posthog_ai_access_decision,
)

from ee.billing.billing_manager import OrganizationFundingStatus, PrepaidCreditState, StartupProgramLabel

RULES = {"cutoff_date": "2026-06-01T00:00:00+00:00", "min_trust_score": 5}


class TestPostHogAIAccessDecision(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "grandfathered_variant_beats_every_deny",
                "grandfathered",
                None,
                "Startup",
                True,
                0,
                "2026-09-01",
                PostHogAIAccessDecision.GRANDFATHERED,
            ),
            ("flag_off_denies", None, RULES, None, False, 9, "2025-01-01", PostHogAIAccessDecision.BETA_OFF),
            ("startup_program", "beta", RULES, "YC", False, 9, "2025-01-01", PostHogAIAccessDecision.STARTUP_PROGRAM),
            ("prepaid_credits", "beta", RULES, None, True, 9, "2025-01-01", PostHogAIAccessDecision.PREPAID_CREDITS),
            (
                "created_after_cutoff",
                "beta",
                RULES,
                None,
                False,
                9,
                "2026-06-01",
                PostHogAIAccessDecision.CREATED_AFTER_CUTOFF,
            ),
            ("low_trust", "beta", RULES, None, False, 4, "2025-01-01", PostHogAIAccessDecision.LOW_TRUST),
            ("passes_every_rule", "beta", RULES, None, False, 5, "2025-01-01", PostHogAIAccessDecision.ALLOWED),
            (
                "beta_without_rules_fails_closed",
                "beta",
                None,
                None,
                False,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.UNRESOLVED,
            ),
            (
                "rules_as_json_string",
                "beta",
                json.dumps(RULES),
                None,
                False,
                5,
                "2025-01-01",
                PostHogAIAccessDecision.ALLOWED,
            ),
            (
                "billing_unavailable_fails_closed",
                "beta",
                RULES,
                None,
                False,
                9,
                "2025-01-01",
                PostHogAIAccessDecision.UNRESOLVED,
                True,
            ),
        ]
    )
    def test_decision(
        self,
        _name: str,
        variant: str | None,
        rules: dict[str, Any] | str | None,
        startup_program_label: StartupProgramLabel | None,
        has_prepaid_credits: bool,
        trust_score: int,
        org_created: str,
        expected: PostHogAIAccessDecision,
        billing_unavailable: bool = False,
    ) -> None:
        cache.clear()
        organization = Organization(
            name="Fixture org",
            created_at=datetime.fromisoformat(org_created).replace(tzinfo=UTC),
            customer_trust_scores={"events": trust_score},
        )
        user = User(email="fixture@example.com", distinct_id="fixture-distinct-id")
        prepaid = PrepaidCreditState.ACTIVE if has_prepaid_credits else PrepaidCreditState.NONE
        access = FeatureFlagResult(
            key="phai-2-beta", enabled=variant is not None, variant=variant, payload=rules, reason=None
        )

        with (
            patch("products.tasks.backend.access.posthoganalytics.get_feature_flag_result", return_value=access),
            patch(
                "products.tasks.backend.access._get_funding_status",
                return_value=OrganizationFundingStatus(
                    startup_program_label=startup_program_label, prepaid_credit_state=prepaid
                ),
                side_effect=DesktopAccessResolutionError("billing unavailable") if billing_unavailable else None,
            ),
        ):
            decision = get_posthog_ai_access_decision(user, organization)

        self.assertEqual(decision, expected)

    @parameterized.expand(
        [
            ("resolved_decision_is_reused", RULES, True, 30, None, True, PostHogAIAccessDecision.ALLOWED, 1),
            (
                "resolved_decision_expires",
                RULES,
                True,
                24 * 60 + 1,
                None,
                True,
                PostHogAIAccessDecision.ALLOWED,
                2,
            ),
            (
                "deciding_flag_edit_busts_it",
                RULES,
                True,
                30,
                "phai-2-beta",
                True,
                PostHogAIAccessDecision.ALLOWED,
                2,
            ),
            (
                "other_flag_edit_keeps_it",
                RULES,
                True,
                30,
                "other-flag",
                True,
                PostHogAIAccessDecision.ALLOWED,
                1,
            ),
            (
                "unloaded_definitions_reused_briefly",
                RULES,
                True,
                0,
                None,
                False,
                PostHogAIAccessDecision.ALLOWED,
                1,
            ),
            (
                "unloaded_definitions_expire_fast",
                RULES,
                True,
                2,
                None,
                False,
                PostHogAIAccessDecision.ALLOWED,
                2,
            ),
            (
                "beta_without_rules_is_not_cached",
                None,
                True,
                30,
                None,
                True,
                PostHogAIAccessDecision.UNRESOLVED,
                2,
            ),
            (
                "failed_beta_lookup_not_cached",
                RULES,
                False,
                30,
                None,
                True,
                PostHogAIAccessDecision.UNRESOLVED,
                2,
            ),
        ]
    )
    def test_cached_decision(
        self,
        _name: str,
        rules: dict[str, Any] | None,
        beta_resolves: bool,
        minutes_between_loads: int,
        edited_flag: str | None,
        definitions_loaded: bool,
        expected: PostHogAIAccessDecision,
        expected_evaluations: int,
    ) -> None:
        cache.clear()
        organization = Organization(
            name="Fixture org", created_at=datetime(2025, 1, 1, tzinfo=UTC), customer_trust_scores={"events": 9}
        )
        user = User(pk=1, email="fixture@example.com", distinct_id="fixture-distinct-id")
        beta = (
            FeatureFlagResult(key="phai-2-beta", enabled=True, variant="beta", payload=rules, reason=None)
            if beta_resolves
            else None
        )
        definitions = [
            {"key": key, "active": True, "filters": {"groups": [{"properties": [], "rollout_percentage": 0}]}}
            for key in ("phai-2-beta", "other-flag")
        ]

        with (
            patch("products.tasks.backend.access.posthoganalytics.get_feature_flag_result", return_value=beta),
            patch(
                "products.tasks.backend.access.posthoganalytics.feature_flag_definitions",
                return_value=definitions if definitions_loaded else None,
            ),
            patch(
                "products.tasks.backend.access._get_funding_status",
                return_value=OrganizationFundingStatus(
                    startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE
                ),
            ),
            patch(
                "products.tasks.backend.access.get_posthog_ai_access_decision", wraps=get_posthog_ai_access_decision
            ) as mock_decision,
            time_machine.travel(datetime(2026, 11, 3, 12, 0, tzinfo=UTC), tick=False) as traveller,
        ):
            first = get_cached_posthog_ai_access_decision(user, organization)
            traveller.shift(timedelta(minutes=minutes_between_loads))
            for definition in definitions:
                if definition["key"] == edited_flag:
                    definition["filters"] = {"groups": [{"properties": [], "rollout_percentage": 100}]}
            second = get_cached_posthog_ai_access_decision(user, organization)

        self.assertEqual((first, second), (expected, expected))
        self.assertEqual(mock_decision.call_count, expected_evaluations)

    def test_server_refusal_refreshes_the_page_render_decision(self) -> None:
        cache.clear()
        organization = Organization(
            name="Fixture org", created_at=datetime(2025, 1, 1, tzinfo=UTC), customer_trust_scores={"events": 9}
        )
        user = User(pk=1, email="fixture@example.com", distinct_id="fixture-distinct-id")
        access = FeatureFlagResult(key="phai-2-beta", enabled=True, variant="beta", payload=RULES, reason=None)

        with (
            patch("products.tasks.backend.access.posthoganalytics.get_feature_flag_result", return_value=access),
            patch("products.tasks.backend.access.posthoganalytics.feature_flag_definitions", return_value=[]),
            patch(
                "products.tasks.backend.access._get_funding_status",
                return_value=OrganizationFundingStatus(
                    startup_program_label=None, prepaid_credit_state=PrepaidCreditState.NONE
                ),
            ),
        ):
            page_before = get_cached_posthog_ai_access_decision(user, organization)
            organization.customer_trust_scores = {"events": 1}
            refused = get_posthog_ai_access_decision(user, organization)
            page_after = get_cached_posthog_ai_access_decision(user, organization)

        self.assertEqual(
            (page_before, refused, page_after),
            (PostHogAIAccessDecision.ALLOWED, PostHogAIAccessDecision.LOW_TRUST, PostHogAIAccessDecision.LOW_TRUST),
        )
