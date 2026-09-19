from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User

from products.security.backend.facade.enums import Effect, Scope, TargetType
from products.security.backend.logic.guards import RuleDraft
from products.security.backend.logic.impact import CountBasis, preview


def _draft(target_type: TargetType, value: str, scope: Scope = Scope.ALL_ACCESS) -> RuleDraft:
    return RuleDraft(target_type=target_type, target_value=value, effect=Effect.BLOCK, scope=scope)


class TestPreview(BaseTest):
    def setUp(self):
        super().setUp()
        for email in [
            "farm.bot@example.com",
            "farm.bot+1@example.com",
            "FARM.BOT+2@Example.com",
            "farmbot@example.com",
            "farm.bot@other.example",
            "sampleuser@gmail.com",
            "s.a.m.p.l.e.user+x@googlemail.com",
            "sample.user@gmail.com",
            "a@mail.example.org",
            "b@example.org",
            "c@notexample.org",
        ]:
            User.objects.create(email=email, first_name="Sample")
        User.objects.create(email="farm.bot+3@example.com", first_name="Sample", is_active=False)

    @parameterized.expand(
        [
            # Outside Gmail the dot is part of the mailbox, so farmbot@ is someone else.
            ("non_gmail_root", TargetType.EMAIL_ROOT, "farm.bot@example.com", 3),
            ("gmail_root_across_dots_and_domains", TargetType.EMAIL_ROOT, "sampleuser@gmail.com", 3),
            ("domain_and_its_subdomains", TargetType.EMAIL_DOMAIN, "example.org", 2),
        ]
    )
    def test_counts_the_active_accounts_the_rule_would_reach(self, _name, target_type, value, expected):
        assert preview(_draft(target_type, value)).matched_active_accounts == expected

    def test_a_signup_rule_reaches_no_existing_account(self):
        impact = preview(_draft(TargetType.EMAIL_ROOT, "farm.bot@example.com", scope=Scope.SIGNUP))

        assert impact.matched_active_accounts is None

    def test_a_count_over_the_cap_stops_at_the_cap(self):
        with patch("products.security.backend.logic.impact.COUNT_CAP", 2):
            impact = preview(_draft(TargetType.EMAIL_ROOT, "farm.bot@example.com"))

        assert (impact.matched_active_accounts, impact.count_capped) == (2, True)

    def test_a_project_rule_counts_the_members_of_its_organization(self):
        impact = preview(_draft(TargetType.TEAM_ID, str(self.team.id)))

        assert (impact.matched_active_accounts, impact.count_basis) == (1, CountBasis.PROJECT_ORGANIZATION)

    def test_a_range_reports_its_size(self):
        assert preview(_draft(TargetType.IP, "93.184.216.0/24")).address_count == 256
