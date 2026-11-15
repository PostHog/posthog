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


class TestRedisBypassEquivalence(SimpleTestCase):
    """What the deleted Redis list did, restated against access rules.

    The old check was one line: `sismember(key, email.lower())`, consulted only for a
    BLOCK or CHALLENGE verdict. Every case below pins a property of that check, so a
    later change to rule matching cannot quietly narrow what used to be exempt.
    """

    @parameterized.expand(
        [
            ("stored lower, sent upper", "legacy@example.org", "LEGACY@EXAMPLE.ORG"),
            ("stored lower, sent mixed", "legacy@example.org", "Legacy@Example.Org"),
            ("stored mixed, sent lower", "Legacy@Example.Org", "legacy@example.org"),
        ]
    )
    def test_case_is_ignored_on_both_sides(self, _name: str, stored: str, sent: str) -> None:
        # `add_radar_bypass_email` lowercased on write and `is_radar_bypass_email` on read,
        # so case never mattered. Rule normalization has to fold both the same way.
        seed_rules(exempt_rule(targetValue=stored, scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, sent, "", "", "93.184.216.1") == "bypass"

    def test_surrounding_whitespace_still_matches(self) -> None:
        # The old check did not trim, so " a@b.c " missed. Rules trim, which is a superset:
        # anything the list exempted is still exempt.
        seed_rules(exempt_rule(targetValue="legacy@example.org", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, " legacy@example.org ", "", "", "93.184.216.1") == "bypass"

    @parameterized.expand(
        [
            ("plus tag", "user+tag@example.org"),
            ("dots moved", "u.s.e.r@example.org"),
            ("different domain", "user@example.com"),
            ("subdomain of the address domain", "user@mail.example.org"),
        ]
    )
    def test_an_exact_address_rule_does_not_widen(self, _name: str, sent: str) -> None:
        # The old list matched the whole string. An address rule has to behave the same, or
        # the cut-over would exempt people the Redis list never did.
        seed_rules(exempt_rule(targetValue="user@example.org", scope="signup_risk"))
        assert _decide_outcome(RadarVerdict.BLOCK, sent, "", "", "93.184.216.1") == "block"

    @parameterized.expand([(RadarVerdict.ALLOW,), (RadarVerdict.ERROR,), (RadarVerdict.DISABLED,)])
    def test_verdicts_that_never_consulted_the_list(self, verdict: RadarVerdict) -> None:
        # The old guard ran only for BLOCK and CHALLENGE. Everything else fell through to
        # "allow" without a lookup, and still must.
        seed_rules(exempt_rule(targetValue="legacy@example.org", scope="signup_risk"))
        assert _decide_outcome(verdict, "legacy@example.org", "", "", "93.184.216.1") == "allow"

    def test_an_expired_rule_does_not_exempt(self) -> None:
        # A Redis entry never expired. A rule can, and that is the one way the new mechanism
        # can be narrower than the old one, so it is pinned: expiry means the verdict stands.
        seed_rules(exempt_rule(targetValue="legacy@example.org", scope="signup_risk", expiresAt="2020-01-01T00:00:00Z"))
        assert _decide_outcome(RadarVerdict.BLOCK, "legacy@example.org", "", "", "93.184.216.1") == "block"

    def test_a_far_future_expiry_still_exempts(self) -> None:
        seed_rules(exempt_rule(targetValue="legacy@example.org", scope="signup_risk", expiresAt="2099-01-01T00:00:00Z"))
        assert _decide_outcome(RadarVerdict.BLOCK, "legacy@example.org", "", "", "93.184.216.1") == "bypass"

    @patch("posthog.workos_radar.verify_turnstile_token", return_value=True)
    @patch("posthog.workos_radar.validate_and_consume_nonce", return_value=True)
    def test_the_challenge_resubmit_path_is_unchanged(self, _nonce: object, _token: object) -> None:
        # A resubmit with a token and nonce returned before the bypass check and never read
        # Redis. It must not read the rules either, or a challenge could resolve differently.
        seed_rules()
        assert (
            _decide_outcome(RadarVerdict.CHALLENGE, "anyone@example.org", "tok", "nonce", "93.184.216.1") == "completed"
        )

    def test_a_domain_rule_covers_the_addresses_a_list_would_have_held(self) -> None:
        # Strictly wider than the old list, and the reason the hub can replace it: one rule
        # covers a domain and its subdomains instead of one entry per address.
        seed_rules(exempt_rule(targetType="email_domain", targetValue="partner.example", scope="signup_risk"))
        for sent in ("a@partner.example", "b@mail.partner.example", "c@deep.mail.partner.example"):
            assert _decide_outcome(RadarVerdict.BLOCK, sent, "", "", "93.184.216.1") == "bypass"
        assert _decide_outcome(RadarVerdict.BLOCK, "d@notpartner.example", "", "", "93.184.216.1") == "block"
