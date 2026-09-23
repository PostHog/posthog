from posthog.test.base import BaseTest
from unittest.mock import patch

from prometheus_client import REGISTRY

from posthog.models import User

from products.security.backend.facade.api import decide, is_email_code_exempt, shadow_check
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Outcome, Surface
from products.security.backend.tests.helpers import block_rule, exempt_rule, seed_rules


def _would_block(call_site: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_would_block_total",
            {"surface": "app", "call_site": call_site, "target_type": "user_uuid"},
        )
        or 0.0
    )


class TestFacade(BaseTest):
    def test_a_uuid_only_subject_is_resolved_before_the_posthog_check(self) -> None:
        staff = User.objects.create_and_join(self.organization, "staff@posthog.com", "password1234")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(staff.uuid)))
        assert decide(SubjectInput(user_uuid=str(staff.uuid)), Surface.APP).outcome == Outcome.ALLOW

    def test_decide_reports_the_rule(self) -> None:
        rule = block_rule(targetType="ip", targetValue="93.184.216.0/24")
        seed_rules(rule)
        decision = decide(SubjectInput(ip="93.184.216.7"), Surface.SIGNUP)
        assert (decision.outcome, decision.rule_id, decision.target_type) == (Outcome.BLOCK, rule["id"], "ip")
        assert decide(SubjectInput(ip="garbage"), Surface.SIGNUP).outcome == Outcome.ALLOW

    def test_email_code_exemption(self) -> None:
        seed_rules(exempt_rule(targetValue="mfa@example.com"))
        assert is_email_code_exempt("MFA@example.com") is True
        assert is_email_code_exempt("other@example.com") is False

    def test_email_code_exemption_fails_closed(self) -> None:
        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")):
            assert is_email_code_exempt("mfa@example.com") is False

    def test_shadow_check_counts_and_never_raises(self) -> None:
        user = User.objects.create_and_join(self.organization, "abuser@example.com", "password1234")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(user.uuid)))
        before = _would_block("test_site")
        shadow_check(SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="test_site")
        assert _would_block("test_site") == before + 1

        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")):
            shadow_check(SubjectInput(email=user.email), Surface.APP, call_site="test_site")
