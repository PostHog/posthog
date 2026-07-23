import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

AccessControl = pytest.importorskip("ee.models.rbac.access_control").AccessControl

pytestmark = [pytest.mark.django_db]

_HELPER = "products.revenue_analytics.backend.api.find_values_for_revenue_analytics_property"


@pytest.mark.ee
class TestRevenueAnalyticsAPIAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.taxonomy_url = f"/api/environments/{self.team.pk}/revenue_analytics/taxonomy/values/"
        self.joins_url = f"/api/environments/{self.team.pk}/revenue_analytics/joins/"
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

    def _member(self, revenue_analytics_level: str) -> User:
        member = User.objects.create_and_join(
            self.organization, f"member-{revenue_analytics_level}@posthog.com", "testtest"
        )
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="revenue_analytics",
            access_level=revenue_analytics_level,
            organization_member=membership,
        )
        return member

    @patch(_HELPER, return_value=["a@b.com"])
    def test_member_denied_revenue_analytics_access_cannot_read_taxonomy_values(self, _mock):
        self.client.force_login(self._member("none"))
        response = self.client.get(self.taxonomy_url, data={"key": "revenue_analytics_customer.email"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch(_HELPER, return_value=["a@b.com"])
    def test_member_with_viewer_access_can_read_taxonomy_values(self, _mock):
        self.client.force_login(self._member("viewer"))
        response = self.client.get(self.taxonomy_url, data={"key": "revenue_analytics_customer.email"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [{"name": "a@b.com"}]

    def test_member_denied_revenue_analytics_access_cannot_change_joins(self):
        self.client.force_login(self._member("none"))
        response = self.client.post(self.joins_url, data={"enabled": True})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_access_cannot_change_joins(self):
        # Joins mutate person-join config, so writing requires editor; viewer-only must be blocked.
        self.client.force_login(self._member("viewer"))
        response = self.client.post(self.joins_url, data={"enabled": True})
        assert response.status_code == status.HTTP_403_FORBIDDEN
