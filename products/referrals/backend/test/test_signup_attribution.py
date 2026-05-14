import uuid
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models import Organization, User

from products.referrals.backend.models import SocialReferral

VALID_TEST_PASSWORD = "mighty-strong-secure-1337!!"


class TestSignupSocialReferralAttribution(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        TEST_clear_instance_license_cache()

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    def test_api_sign_up_records_social_referral_attribution(self, mock_capture):
        Organization.objects.create(name="PostHog Internal Metrics", for_internal_metrics=True)
        _referrer_org, _referrer_team, referrer = User.objects.bootstrap(
            organization_name="Referrer Org",
            email="referrer@posthogsignup.test",
            password=VALID_TEST_PASSWORD,
            first_name="Alice",
        )
        referrer.distinct_id = "ph_distinct_stable_referrer"
        referrer.save(update_fields=["distinct_id"])

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "Bob",
                "email": "bob_referred@posthogsignup.test",
                "password": VALID_TEST_PASSWORD,
                "organization_name": "Bob Org",
                "role_at_organization": "product",
                "referral_program_id": "ph_distinct_stable_referrer",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        bob = cast(User, User.objects.get(email="bob_referred@posthogsignup.test"))
        bob_organization = bob.organization
        self.assertIsNotNone(bob_organization)

        referral = (
            SocialReferral.objects.filter(organization_id=referrer.organization_id, user_id=referrer.pk)
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(referral)
        referee_state = cast(dict[str, Any], referral.referee_state)
        self.assertEqual(referee_state[str(bob_organization.id)], {"first_event_sent": False})

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    def test_api_sign_up_unknown_referral_distinct_id_does_not_break_signup(self, mock_capture):
        Organization.objects.create(name="PostHog Internal Metrics", for_internal_metrics=True)
        referrals_before = SocialReferral.objects.count()

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "Charlie",
                "email": "charlie_noref@posthogsignup.test",
                "password": VALID_TEST_PASSWORD,
                "organization_name": "Charlie Org",
                "role_at_organization": "product",
                "referral_program_id": "no_such_user_distinct_xx",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SocialReferral.objects.count(), referrals_before)

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    def test_api_sign_up_social_referral_appends_org_to_existing_referee_state(self, mock_capture):
        Organization.objects.create(name="PostHog Internal Metrics", for_internal_metrics=True)
        referrer_organization, _t, referrer = User.objects.bootstrap(
            organization_name="Referrer Org Merge",
            email="alice_merge@posthogsignup.test",
            password=VALID_TEST_PASSWORD,
            first_name="Alice",
        )
        referrer.distinct_id = "ph_distinct_merge_referrer"
        referrer.save(update_fields=["distinct_id"])

        prior_org_key = str(uuid.uuid4())
        SocialReferral.objects.create(
            organization_id=referrer_organization.id,
            user_id=referrer.pk,
            referee_state={prior_org_key: {"first_event_sent": True}},
        )

        resp_bob = self.client.post(
            "/api/signup/",
            {
                "first_name": "Bob",
                "email": "bob_merge@posthogsignup.test",
                "password": VALID_TEST_PASSWORD,
                "organization_name": "Bob Merge Org",
                "role_at_organization": "product",
                "referral_program_id": "ph_distinct_merge_referrer",
            },
        )
        self.assertEqual(resp_bob.status_code, status.HTTP_201_CREATED)

        bob_user = cast(User, User.objects.get(email="bob_merge@posthogsignup.test"))
        bob_organization = cast(Organization, bob_user.organization)

        referral_qs = SocialReferral.objects.filter(
            organization_id=referrer_organization.id,
            user_id=referrer.pk,
        ).order_by("-created_at")
        self.assertEqual(referral_qs.count(), 1)
        referral = referral_qs.first()
        assert referral is not None
        referral.refresh_from_db()
        self.assertEqual(
            referral.referee_state[prior_org_key],
            {"first_event_sent": True},
        )
        self.assertEqual(
            referral.referee_state[str(bob_organization.id)],
            {"first_event_sent": False},
        )

        resp_dana = self.client.post(
            "/api/signup/",
            {
                "first_name": "Dana",
                "email": "dana_merge@posthogsignup.test",
                "password": VALID_TEST_PASSWORD,
                "organization_name": "Dana Merge Org",
                "role_at_organization": "engineering",
                "referral_program_id": "ph_distinct_merge_referrer",
            },
        )
        self.assertEqual(resp_dana.status_code, status.HTTP_201_CREATED)

        dana_user = cast(User, User.objects.get(email="dana_merge@posthogsignup.test"))
        dana_organization = cast(Organization, dana_user.organization)

        referral.refresh_from_db()
        referee_state_final = cast(dict[str, Any], referral.referee_state)
        self.assertEqual(referee_state_final[prior_org_key], {"first_event_sent": True})
        self.assertEqual(referee_state_final[str(bob_organization.id)], {"first_event_sent": False})
        self.assertEqual(referee_state_final[str(dana_organization.id)], {"first_event_sent": False})
