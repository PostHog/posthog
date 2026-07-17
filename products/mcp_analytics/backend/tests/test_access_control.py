import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControlError

from products.mcp_analytics.backend.hogql_queries.base import validate_mcp_analytics_access
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


# Guards that "mcp_analytics" being registered in ACCESS_CONTROL_RESOURCES is actually enforced
# end-to-end through a real viewset - generic level-comparison and org-admin-bypass mechanics are
# already covered by posthog/rbac/test/test_user_access_control_pbt.py for every registered resource.
@pytest.mark.ee
class TestMCPAnalyticsAccessControl(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=None,
            role=None,
        )

    def _login_with_access_level(self, access_level: str) -> User:
        user = User.objects.create_and_join(self.organization, f"mcp-{access_level}@posthog.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="mcp_analytics",
            resource_id=None,
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )
        self.client.force_login(user)
        return user

    @parameterized.expand(
        [
            ("none", status.HTTP_403_FORBIDDEN),
            ("viewer", status.HTTP_200_OK),
            ("editor", status.HTTP_200_OK),
        ]
    )
    def test_list_feedback_by_access_level(self, access_level: str, expected_status: int) -> None:
        self._login_with_access_level(access_level)

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/feedback/")

        assert response.status_code == expected_status

    @parameterized.expand(
        [
            ("none", status.HTTP_403_FORBIDDEN),
            ("viewer", status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_201_CREATED),
        ]
    )
    def test_create_feedback_by_access_level(self, access_level: str, expected_status: int) -> None:
        self._login_with_access_level(access_level)

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/feedback/",
            {"goal": "understand usage", "feedback": "Need clearer results"},
            format="json",
        )

        assert response.status_code == expected_status

    @parameterized.expand(
        [
            ("none", True),
            ("viewer", False),
            ("editor", False),
        ]
    )
    def test_validate_mcp_analytics_access_enforces_rbac(self, access_level: str, should_raise: bool) -> None:
        # Guards the query-runner path: MCP*Query kinds run through the generic /query/ endpoint
        # (scope_object "query"), not the mcp_analytics viewsets above, so without this check a
        # user denied "mcp_analytics" access could still read the same data via a direct query.
        user = self._login_with_access_level(access_level)

        if should_raise:
            with self.assertRaises(UserAccessControlError):
                validate_mcp_analytics_access(self.team, user)
        else:
            assert validate_mcp_analytics_access(self.team, user) is True

    def test_validate_mcp_analytics_access_allows_default_access_without_explicit_grant(self) -> None:
        user = User.objects.create_and_join(self.organization, "mcp-default@posthog.com", "testtest")

        assert validate_mcp_analytics_access(self.team, user) is True
