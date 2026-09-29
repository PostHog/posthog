from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.workos_radar import RadarVerdict, _decide_outcome, add_radar_bypass_email

from products.security.backend.tests.helpers import exempt_rule, seed_rules


class TestRadarCallSite(SimpleTestCase):
    @parameterized.expand([(RadarVerdict.BLOCK,), (RadarVerdict.CHALLENGE,)])
    def test_exempt_address_bypasses(self, verdict: RadarVerdict) -> None:
        seed_rules(exempt_rule(targetType="email_domain", targetValue="partner.example", scope="signup_risk"))
        assert _decide_outcome(verdict, "new@eu.partner.example", "", "", "93.184.216.1") == "bypass_rule"

    def test_other_addresses_keep_the_verdict(self) -> None:
        seed_rules(exempt_rule(targetValue="trusted@example.org", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, "someone@example.org", "", "", "93.184.216.1") == "block"
        assert _decide_outcome(RadarVerdict.ALLOW, "trusted@example.org", "", "", "93.184.216.1") == "allow"

    def test_email_code_exemption_does_not_bypass_radar(self) -> None:
        seed_rules(exempt_rule(targetValue="mfa@example.org"))
        assert _decide_outcome(RadarVerdict.BLOCK, "mfa@example.org", "", "", "93.184.216.1") == "block"

    def test_legacy_redis_bypass_still_works(self) -> None:
        seed_rules()
        add_radar_bypass_email("legacy@example.org")
        assert _decide_outcome(RadarVerdict.BLOCK, "legacy@example.org", "", "", "93.184.216.1") == "bypass_legacy"

    def test_the_legacy_list_wins_the_label_when_both_match(self) -> None:
        seed_rules(exempt_rule(targetValue="both@example.org", scope="signup_risk"))
        add_radar_bypass_email("both@example.org")
        assert _decide_outcome(RadarVerdict.BLOCK, "both@example.org", "", "", "93.184.216.1") == "bypass_legacy"

    def test_a_target_type_the_hub_forbids_does_not_exempt(self) -> None:
        seed_rules(exempt_rule(targetType="everyone", targetValue="", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, "anyone@example.org", "", "", "93.184.216.1") == "block"
