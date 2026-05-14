from posthog.test.base import APIBaseTest

from posthog.models import Organization

from products.referrals.backend.models import SocialReferral


class TestSocialReferralAPI(APIBaseTest):
    def test_list_includes_referee_invite_organization_names(self) -> None:
        invited = Organization.objects.create(name="Invited Co")
        SocialReferral.objects.create(
            organization_id=self.organization.id,
            user_id=self.user.id,
            referee_state={str(invited.id): {"first_event_sent": False}},
        )

        response = self.client.get(f"/api/organizations/{self.organization.id}/social_referrals/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        invites = results[0]["referee_invites"]
        self.assertEqual(len(invites), 1)
        self.assertEqual(invites[0]["organization_name"], "Invited Co")
        self.assertEqual(invites[0]["first_event_sent"], False)
        self.assertIsNone(invites[0]["signed_up_at"])
        self.assertIsNone(invites[0]["signed_up_user_id"])
        self.assertIsNone(invites[0]["signed_up_user_display_name"])
        self.assertEqual(invites[0]["shopify_discount_codes"], [])
        self.assertEqual(invites[0]["organization_id"], str(invited.id))
