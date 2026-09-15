import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.gates import (
    SignupIdentity,
    SignupIdentitySkip,
    domain_from_email,
    enrichment_enabled,
    region_allowed,
    resolve_signup_identity,
)

_MODULE = "products.growth.backend.enrichment.gates"


class TestEnrichmentGates(BaseTest):
    def _org_with_member(self, email: str) -> Organization:
        organization = Organization.objects.create(name=email)
        user = User.objects.create_user(email=email, password=None, first_name="signup")
        OrganizationMembership.objects.create(organization=organization, user=user)
        return organization

    def test_resolve_signup_identity_with_no_membership_is_unusable(self):
        organization = Organization.objects.create(name="empty.example")

        assert resolve_signup_identity(str(organization.id)) == SignupIdentitySkip(reason="no_usable_member")

    def test_resolve_signup_identity_after_the_membership_window_has_left(self):
        organization = self._org_with_member("founder@late.example")
        OrganizationMembership.objects.filter(organization=organization).update(
            joined_at=organization.created_at + dt.timedelta(minutes=10)
        )

        assert resolve_signup_identity(str(organization.id)) == SignupIdentitySkip(reason="signup_user_left")

    def test_resolve_signup_identity_with_a_generic_email_is_unusable(self):
        organization = self._org_with_member("founder@gmail.com")

        assert resolve_signup_identity(str(organization.id)) == SignupIdentitySkip(reason="no_usable_member")

    def test_resolve_signup_identity_with_a_work_email_returns_a_lowercased_identity(self):
        organization = self._org_with_member("Founder@Stripe.com")
        distinct_id = organization.memberships.get().user.distinct_id
        assert distinct_id is not None

        assert resolve_signup_identity(str(organization.id)) == SignupIdentity(
            distinct_id=distinct_id, domain="stripe.com"
        )

    @parameterized.expand(
        [
            ("mixed_case", "Founder@Stripe.COM", "stripe.com"),
            ("display_name_form", "Name <a@B.com>", "b.com"),
            ("no_at", "not-an-email", None),
            ("empty", "", None),
        ]
    )
    def test_domain_from_email(self, _name, email, expected):
        assert domain_from_email(email) == expected

    @parameterized.expand([("us", "US", True), ("eu", "EU", True), ("self_hosted", None, False)])
    def test_region_allowed(self, _name, region, expected):
        with patch(f"{_MODULE}.get_instance_region", return_value=region):
            assert region_allowed() is expected

    def test_enrichment_enabled_reflects_the_instance_setting(self):
        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", True):
            assert enrichment_enabled() is True
        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            assert enrichment_enabled() is False
