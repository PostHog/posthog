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
            (
                "rules_as_json_string",
                set(),
                True,
                json.dumps(RULES),
                None,
                False,
                5,
                "2025-01-01",
                PostHogAIAccessDecision.ALLOWED,
            ),
            (
                "billing_unavailable_fails_closed",
                set(),
                True,
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
        grandfathered_flags: set[str],
        beta_enabled: bool,
        rules: dict[str, Any] | str | None,
        startup_program_label: StartupProgramLabel | None,
        has_prepaid_credits: bool,
        trust_score: int,
        org_created: str,
        expected: PostHogAIAccessDecision,
        billing_unavailable: bool = False,
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
                side_effect=DesktopAccessResolutionError("billing unavailable") if billing_unavailable else None,
            ),
        ):
            decision = get_posthog_ai_access_decision(user, organization)

        self.assertEqual(decision, expected)

    @parameterized.expand(
        [
            ("resolved_decision_is_reused", False, RULES, True, 30, None, True, PostHogAIAccessDecision.ALLOWED, 1),
            (
                "resolved_decision_expires",
                False,
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
                False,
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
                False,
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
                False,
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
                False,
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
                False,
                None,
                True,
                30,
                None,
                True,
                PostHogAIAccessDecision.UNRESOLVED,
                2,
            ),
            (
                "failed_override_lookup_not_cached",
                None,
                RULES,
                True,
                30,
                None,
                True,
                PostHogAIAccessDecision.UNRESOLVED,
                2,
            ),
            (
                "failed_beta_lookup_not_cached",
                False,
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
        override_value: bool | None,
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
            FeatureFlagResult(key="phai-2-beta", enabled=True, variant=None, payload=rules, reason=None)
            if beta_resolves
            else None
        )
        definitions = [
            {"key": key, "active": True, "filters": {"groups": [{"properties": [], "rollout_percentage": 0}]}}
            for key in ("phai-2-beta", "other-flag")
        ]

        with (
            patch("products.tasks.backend.access.get_feature_flag_or_none", return_value=override_value),
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
