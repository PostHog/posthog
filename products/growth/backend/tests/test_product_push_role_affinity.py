from collections import Counter

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.schema_enums import ProductKey

from products.growth.backend.product_push.role_affinity import (
    BASE_WEIGHT,
    MAX_ROLE_BOOST,
    get_role_counts,
    pick_by_role_affinity,
    weights_for_roles,
)

CANDIDATES = [ProductKey.DATA_WAREHOUSE, ProductKey.MARKETING_ANALYTICS, ProductKey.LOGS]


class TestWeightsForRoles(SimpleTestCase):
    @parameterized.expand(
        [
            # Nobody stated a role we map, so every candidate stays equally likely.
            ("no stated roles", Counter(), [BASE_WEIGHT, BASE_WEIGHT, BASE_WEIGHT]),
            ("no role we map", Counter({"student": 3}), [BASE_WEIGHT, BASE_WEIGHT, BASE_WEIGHT]),
            (
                "every member favors one product",
                Counter({"data": 4}),
                [BASE_WEIGHT + MAX_ROLE_BOOST, BASE_WEIGHT, BASE_WEIGHT],
            ),
            (
                "the boost splits with the share of members",
                Counter({"data": 3, "marketing": 1}),
                [BASE_WEIGHT + MAX_ROLE_BOOST * 0.75, BASE_WEIGHT + MAX_ROLE_BOOST * 0.25, BASE_WEIGHT],
            ),
            # 'student' has no affinity entry, so it neither boosts nor dilutes the data person.
            (
                "unmapped roles stay out of the denominator",
                Counter({"data": 1, "student": 9}),
                [BASE_WEIGHT + MAX_ROLE_BOOST, BASE_WEIGHT, BASE_WEIGHT],
            ),
        ]
    )
    def test_weights(self, _name: str, role_counts: Counter, expected: list[float]) -> None:
        assert weights_for_roles(role_counts, CANDIDATES) == expected


class TestGetRoleCounts(BaseTest):
    def _member(self, organization: Organization, email: str, role: str | None) -> None:
        user = User.objects.create_user(email=email, password=None, first_name="member", role_at_organization=role)
        OrganizationMembership.objects.create(organization=organization, user=user)

    def test_counts_only_this_orgs_members_who_stated_a_role(self) -> None:
        self._member(self.organization, "analyst@example.com", "data")
        self._member(self.organization, "intern@example.com", "student")
        self._member(self.organization, "quiet@example.com", None)
        self._member(Organization.objects.create(name="other"), "elsewhere@example.com", "marketing")

        assert get_role_counts(self.organization) == Counter({"data": 1, "student": 1})
        assert pick_by_role_affinity(self.organization, CANDIDATES) in CANDIDATES
