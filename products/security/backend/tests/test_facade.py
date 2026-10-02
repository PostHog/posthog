from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import User

from products.security.backend.facade.api import (
    access_refused,
    decide,
    gateway_credentials_revoked,
    is_email_code_exempt,
    is_enforced,
    is_signup_risk_exempt,
)
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Outcome, Surface
from products.security.backend.tests.helpers import block_rule, enforcing, exempt_rule, seed_rules


def _would_block(call_site: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_would_block_total",
            {"surface": "app", "call_site": call_site, "target_type": "user_uuid"},
        )
        or 0.0
    )


def _decisions(surface: str, call_site: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_decisions_total",
            {"surface": surface, "call_site": call_site, "outcome": outcome},
        )
        or 0.0
    )


def _refusals(call_site: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_refusals_total",
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

    def test_signup_risk_exemption(self) -> None:
        seed_rules(exempt_rule(targetValue="trusted@example.org", scope="signup_risk"))
        assert is_signup_risk_exempt("Trusted@example.org") is True
        assert is_email_code_exempt("trusted@example.org") is False
        assert is_signup_risk_exempt("other@example.org") is False

    def test_signup_risk_exemption_fails_closed(self) -> None:
        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")):
            assert is_signup_risk_exempt("trusted@example.org") is False

    def test_email_code_exemption_fails_closed(self) -> None:
        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")):
            assert is_email_code_exempt("mfa@example.com") is False

    def test_access_refused_counts_every_decision_and_never_raises(self) -> None:
        user = User.objects.create_and_join(self.organization, "abuser@example.com", "password1234")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(user.uuid)))
        before = _would_block("test_site")
        blocked_before = _decisions("app", "test_site", "block")
        access_refused(SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="test_site")
        assert _would_block("test_site") == before + 1
        assert _decisions("app", "test_site", "block") == blocked_before + 1

        # An allow must be counted too. When no block rule matches, every decision is an
        # allow, so a counter that moved only on a block would have no series exactly when
        # there is nothing to block, which is the case it exists to distinguish.
        allowed_before = _decisions("app", "test_site", "allow")
        access_refused(SubjectInput(email="someone@example.com"), Surface.APP, call_site="test_site")
        assert _decisions("app", "test_site", "allow") == allowed_before + 1

        # A decision that raised is an error, not an evaluation, and must not be counted twice.
        allowed_before = _decisions("app", "test_site", "allow")
        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")):
            access_refused(SubjectInput(email=user.email), Surface.APP, call_site="test_site")
        assert _decisions("app", "test_site", "allow") == allowed_before

    @parameterized.expand(
        [
            ("email_code exempt", "email_code", "email_code", "listed@example.com", "exempt"),
            ("email_code allow", "email_code", "email_code", "other@example.com", "allow"),
            ("signup_risk exempt", "signup_risk", "signup_risk", "listed@example.com", "exempt"),
            ("signup_risk allow", "signup_risk", "signup_risk", "other@example.com", "allow"),
        ]
    )
    def test_exemption_checks_count_every_decision(
        self, _name: str, scope: str, surface: str, address: str, outcome: str
    ) -> None:
        # The exemption checks do not go through access_refused, so they need their own count
        # to show that they ran.
        seed_rules(exempt_rule(targetValue="listed@example.com", scope=scope))
        check = is_email_code_exempt if surface == "email_code" else is_signup_risk_exempt
        before = _decisions(surface, surface, outcome)
        check(address)
        assert _decisions(surface, surface, outcome) == before + 1

    @parameterized.expand(
        [
            ("surface enforced", ["app"], True),
            ("another surface enforced", ["signup", "ai_gateway"], False),
            ("nothing enforced", [], False),
        ]
    )
    def test_access_refused_only_on_an_enforced_surface(self, _name: str, enforced: list[str], expected: bool) -> None:
        user = User.objects.create_and_join(self.organization, "abuser@example.com", "password1234")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(user.uuid)))
        refused_before, would_block_before = _refusals("refuse_site"), _would_block("refuse_site")

        with enforcing(*enforced):
            result = access_refused(
                SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="refuse_site"
            )

        assert result is expected
        assert _refusals("refuse_site") == refused_before + (1 if expected else 0)
        assert _would_block("refuse_site") == would_block_before + (0 if expected else 1)

    def test_access_refused_refuses_nobody_when_the_decision_fails(self) -> None:
        seed_rules(block_rule(targetValue="blocked@example.com"))
        with (
            enforcing("app"),
            patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("boom")),
        ):
            assert (
                access_refused(SubjectInput(email="blocked@example.com"), Surface.APP, call_site="refuse_site") is False
            )

    @parameterized.expand([("gateway enforced", ["ai_gateway"], True), ("gateway in shadow", ["signup", "app"], False)])
    def test_gateway_credentials_are_revoked_only_while_the_gateway_is_enforced(
        self, _name: str, enforced: list[str], expected: bool
    ) -> None:
        seed_rules(block_rule(targetValue="abuser@example.com", scope="ai_gateway"))
        would_block_before = REGISTRY.get_sample_value(
            "posthog_security_access_would_block_total",
            {"surface": "ai_gateway", "call_site": "revoke_sweep", "target_type": "email"},
        )

        with enforcing(*enforced):
            assert gateway_credentials_revoked(SubjectInput(email="abuser@example.com")) is expected

        # The sweep re-reads every credential every few minutes, so a would-block from it would
        # swamp the shadow data the flip depends on.
        assert (
            REGISTRY.get_sample_value(
                "posthog_security_access_would_block_total",
                {"surface": "ai_gateway", "call_site": "revoke_sweep", "target_type": "email"},
            )
            == would_block_before
        )

    @parameterized.expand(
        [
            ("payload turns the surface on", {"signup": True}, True),
            ("payload arrives as JSON text", '{"signup": true}', True),
            ("payload leaves the surface off", {"signup": False, "app": True}, False),
            ("a truthy value that is not true", {"signup": "false"}, False),
            ("no payload, or no definitions yet", None, False),
            ("payload that is not an object", '["signup"]', False),
        ]
    )
    def test_is_enforced_reads_only_a_literal_true_from_the_flag_payload(
        self, _name: str, payload: object, expected: bool
    ) -> None:
        with patch(
            "products.security.backend.logic.enforcement.posthoganalytics.get_feature_flag_payload",
            return_value=payload,
        ):
            assert is_enforced(Surface.SIGNUP) is expected

    def test_is_enforced_leaves_the_surface_logging_only_when_the_flag_cannot_be_read(self) -> None:
        with patch(
            "products.security.backend.logic.enforcement.posthoganalytics.get_feature_flag_payload",
            side_effect=RuntimeError("definitions unavailable"),
        ):
            assert is_enforced(Surface.SIGNUP) is False
