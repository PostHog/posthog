from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.workos_radar import RadarVerdict, _decide_outcome

from products.security.backend.tests.helpers import exempt_rule, seed_rules


class TestRadarCallSite(SimpleTestCase):
    @parameterized.expand([(RadarVerdict.BLOCK,), (RadarVerdict.CHALLENGE,)])
    def test_exempt_address_bypasses(self, verdict: RadarVerdict) -> None:
        seed_rules(exempt_rule(targetType="email_domain", targetValue="partner.example", scope="signup_risk"))
        assert _decide_outcome(verdict, "new@eu.partner.example", "", "", "93.184.216.1") == "bypass"

    def test_other_addresses_keep_the_verdict(self) -> None:
        seed_rules(exempt_rule(targetValue="trusted@example.org", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, "someone@example.org", "", "", "93.184.216.1") == "block"
        assert _decide_outcome(RadarVerdict.ALLOW, "trusted@example.org", "", "", "93.184.216.1") == "allow"

    def test_email_code_exemption_does_not_bypass_radar(self) -> None:
        seed_rules(exempt_rule(targetValue="mfa@example.org"))
        assert _decide_outcome(RadarVerdict.BLOCK, "mfa@example.org", "", "", "93.184.216.1") == "block"

    def test_an_address_with_no_rule_is_refused(self) -> None:
        # The Redis list used to answer here. With it gone, an address nobody wrote a rule
        # for keeps the verdict instead of being waved through.
        seed_rules()
        assert _decide_outcome(RadarVerdict.BLOCK, "legacy@example.org", "", "", "93.184.216.1") == "block"

    def test_a_target_type_the_hub_forbids_does_not_exempt(self) -> None:
        seed_rules(exempt_rule(targetType="everyone", targetValue="", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, "anyone@example.org", "", "", "93.184.216.1") == "block"

    def test_an_unreadable_snapshot_keeps_the_verdict(self) -> None:
        # The rule check is now the only bypass, so its failure mode matters more than it
        # did: it swallows errors and returns False, refusing the signup rather than
        # waving it through.
        seed_rules(exempt_rule(targetValue="trusted@example.org", scope="signup_risk"))
        with patch("products.security.backend.facade.api.current_snapshot", side_effect=RuntimeError("redis down")):
            assert _decide_outcome(RadarVerdict.BLOCK, "trusted@example.org", "", "", "93.184.216.1") == "block"
