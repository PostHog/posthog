from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.chat_link_codes import mint_link_code, redeem_link_code
from products.slack_app.backend.services.whatsapp_link import (
    handle_link_redemption,
    link_command_code,
    mint_whatsapp_link_code,
)

WA_ID = "15550001111"


class TestLinkCommandParsing(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", "link abc123", "abc123"),
            ("case_insensitive", "LINK abc123", "abc123"),
            ("surrounding_whitespace", "  link abc123  ", "abc123"),
            ("bare_command", "link", ""),
            ("not_a_command", "hello there", None),
            ("prefix_only_word", "linkage broke", None),
        ]
    )
    def test_link_command_code(self, _name, text, expected):
        assert link_command_code(text) == expected


class TestWhatsAppLinkRedemption(TestCase):
    def setUp(self):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

    def _redeem(self, code: str) -> str:
        return handle_link_redemption(wa_id=WA_ID, profile_name="Vojta", text=f"link {code}")

    def test_link_redemption_links_minter_and_binds_dm_once(self):
        code = mint_whatsapp_link_code(posthog_user_id=self.user.id, team_id=self.team.id)

        reply = self._redeem(code)

        assert self.team.name in reply
        link = UserIntegration.objects.get(kind="whatsapp", integration_id=WA_ID)
        assert link.user_id == self.user.id
        binding = Integration.objects.get(kind="whatsapp", integration_id=WA_ID)
        assert binding.team_id == self.team.id

        # One-shot: replaying the same code must not work.
        replay = self._redeem(code)
        assert "expired or was already used" in replay

    def test_codes_are_provider_scoped(self):
        # A Telegram code pasted into WhatsApp (or vice versa) must not redeem — the
        # shared cache module scopes codes per provider, and collapsing that scoping
        # would let one surface's minting flow bind the other's chats.
        code = mint_link_code(provider="telegram", purpose="link", posthog_user_id=self.user.id, team_id=self.team.id)

        reply = self._redeem(code)

        assert "expired or was already used" in reply
        assert not Integration.objects.filter(kind="whatsapp", integration_id=WA_ID).exists()
        # And the Telegram code survives untouched for its own surface.
        assert redeem_link_code("telegram", code, expected_purpose="link") is not None

    def test_org_mismatch_rejected(self):
        code = mint_whatsapp_link_code(posthog_user_id=self.user.id, team_id=self.team.id)
        OrganizationMembership.objects.filter(user=self.user).delete()

        reply = self._redeem(code)

        assert "isn't a member" in reply
        assert not UserIntegration.objects.filter(kind="whatsapp", integration_id=WA_ID).exists()

    def test_refuses_chat_bound_to_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        Integration.objects.create(team=other_team, kind="whatsapp", integration_id=WA_ID)
        code = mint_whatsapp_link_code(posthog_user_id=self.user.id, team_id=self.team.id)

        reply = self._redeem(code)

        assert "already connected to another PostHog project" in reply
        assert Integration.objects.get(kind="whatsapp", integration_id=WA_ID).team_id == other_team.id
