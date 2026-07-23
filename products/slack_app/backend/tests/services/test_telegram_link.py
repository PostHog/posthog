from django.core.cache import cache
from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services.telegram_link import (
    handle_connect_redemption,
    handle_start_redemption,
    mint_link_code,
    redeem_link_code,
)

TELEGRAM_USER_ID = 777001


def _dm_message(text: str, *, sender_id: int = TELEGRAM_USER_ID, chat_id: int = TELEGRAM_USER_ID) -> dict:
    return {
        "message_id": 10,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": sender_id, "username": "vojta_tg"},
        "text": text,
    }


def _group_message(text: str, *, sender_id: int = TELEGRAM_USER_ID, chat_id: int = -100555) -> dict:
    return {
        "message_id": 11,
        "chat": {"id": chat_id, "type": "supergroup", "title": "Eng"},
        "from": {"id": sender_id, "username": "vojta_tg"},
        "text": text,
    }


class TestTelegramLinkRedemption(TestCase):
    def setUp(self):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

    def _link(self) -> None:
        code = mint_link_code(purpose="link", posthog_user_id=self.user.id, team_id=self.team.id)
        handle_start_redemption(_dm_message(f"/start {code}"))

    def test_start_redemption_links_minter_and_binds_dm_once(self):
        code = mint_link_code(purpose="link", posthog_user_id=self.user.id, team_id=self.team.id)

        reply = handle_start_redemption(_dm_message(f"/start {code}"))

        assert self.team.name in reply
        link = UserIntegration.objects.get(kind="telegram", integration_id=str(TELEGRAM_USER_ID))
        assert link.user_id == self.user.id
        binding = Integration.objects.get(kind="telegram", integration_id=str(TELEGRAM_USER_ID))
        assert binding.team_id == self.team.id

        # One-shot: replaying the same code must not work.
        replay = handle_start_redemption(_dm_message(f"/start {code}"))
        assert "expired or was already used" in replay

    def test_purpose_mismatch_rejected(self):
        # A DM-link code pasted as /connect in a group must not bind the group.
        code = mint_link_code(purpose="link", posthog_user_id=self.user.id, team_id=self.team.id)

        reply = handle_connect_redemption(_group_message(f"/connect {code}"))

        assert "expired or was already used" in reply
        assert not Integration.objects.filter(kind="telegram", integration_id="-100555").exists()
        # And the code is burned either way.
        assert redeem_link_code(code, expected_purpose="link") is None

    def test_connect_redemption_rejects_non_minter_sender(self):
        # The /connect command is visible to the whole group; only the minter's linked
        # Telegram identity may redeem it.
        self._link()
        other = User.objects.create(email="other@example.com", distinct_id="user-2")
        OrganizationMembership.objects.create(user=other, organization=self.organization)
        code = mint_link_code(purpose="connect", posthog_user_id=other.id, team_id=self.team.id)

        reply = handle_connect_redemption(_group_message(f"/connect {code}", sender_id=TELEGRAM_USER_ID))

        assert "Only the person who generated this code" in reply
        assert not Integration.objects.filter(kind="telegram", integration_id="-100555").exists()

    def test_connect_binds_group_for_minter(self):
        self._link()
        code = mint_link_code(purpose="connect", posthog_user_id=self.user.id, team_id=self.team.id)

        reply = handle_connect_redemption(_group_message(f"/connect@PostHogBot {code}"))

        assert "Connected this chat" in reply
        binding = Integration.objects.get(kind="telegram", integration_id="-100555")
        assert binding.team_id == self.team.id

    def test_connect_refuses_chat_bound_to_another_team(self):
        self._link()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        Integration.objects.create(team=other_team, kind="telegram", integration_id="-100555")
        code = mint_link_code(purpose="connect", posthog_user_id=self.user.id, team_id=self.team.id)

        reply = handle_connect_redemption(_group_message(f"/connect {code}"))

        assert "already connected to another PostHog project" in reply
        assert Integration.objects.get(kind="telegram", integration_id="-100555").team_id == other_team.id
