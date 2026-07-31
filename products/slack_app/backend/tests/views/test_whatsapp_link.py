from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User


class TestWhatsAppLinkStartView(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

    @patch(
        "products.slack_app.backend.views.whatsapp_link.get_bot_phone_number",
        return_value="15550253483",
    )
    def test_member_is_redirected_to_deep_link_with_prefilled_command(self, _mock_number):
        self.client.force_login(self.user)
        response = self.client.get(f"/whatsapp/link/start/?team_id={self.team.id}")
        assert response.status_code == 302
        assert response["Location"].startswith("https://wa.me/15550253483?text=link%20")

    def test_requires_login(self):
        response = self.client.get(f"/whatsapp/link/start/?team_id={self.team.id}")
        assert response.status_code == 302
        assert "/login" in response["Location"]

    @patch(
        "products.slack_app.backend.views.whatsapp_link.get_bot_phone_number",
        return_value="15550253483",
    )
    def test_non_member_cannot_mint_for_foreign_team(self, _mock_number):
        # Minting a code against another org's team would let an outsider link/bind
        # into that org via the redemption flow.
        outsider = User.objects.create(email="outsider@example.com", distinct_id="user-2")
        other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(user=outsider, organization=other_org)
        self.client.force_login(outsider)

        response = self.client.get(f"/whatsapp/link/start/?team_id={self.team.id}")

        assert response.status_code == 404
