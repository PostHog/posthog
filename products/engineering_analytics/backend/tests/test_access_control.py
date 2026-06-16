"""Per-user warehouse RBAC on the engineering_analytics read endpoints.

The curated queries run via execute_hogql_query(team=...) with no request user, and HogQL does
not enforce per-user ACL on DataWarehouseTables. So the GitHub-source resolver is the only place
that can honor a user's per-source warehouse access. These tests assert a non-admin user denied a
specific GitHub source cannot read its PR/CI data through the endpoint -- neither by naming it via
source_id nor by it being the default-oldest source -- while an allowed user still can.

The curated HogQL run is stubbed to empty results so the test isolates the resolver's
access-control decision: a resolved source yields 200, a blocked source raises
GitHubSourceNotConnectedError -> 400. Whether the resolver lets a denied source through is exactly
the bug under test, independent of object-storage availability for the real warehouse read.
"""

from types import SimpleNamespace

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.engineering_analytics.backend.tests.test_views import connect_github_source_without_data
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass

# Every curated query runs HogQL through this method; stub it to empty so a resolved source
# returns 200 with no rows, leaving the resolver's access-control decision as the only variable.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"


@pytest.mark.ee
class TestEngineeringAnalyticsAccessControl(APIBaseTest):
    """A team with two connected GitHub sources, A (oldest) and B. ``denied_user`` is a plain
    org member explicitly denied object access to B; ``allowed_user`` keeps default access."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.denied_user = User.objects.create_and_join(self.organization, "denied@posthog.com", "testtest")
        self.allowed_user = User.objects.create_and_join(self.organization, "allowed@posthog.com", "testtest")

        # Two usable GitHub sources (both endpoints synced over ORM-only tables, no object storage).
        # A is created first, so the default-oldest path selects A.
        connect_github_source_without_data(self.team, prefix="sourcea")
        connect_github_source_without_data(self.team, prefix="sourceb")
        self.source_a, self.source_b = ExternalDataSource.objects.order_by("created_at", "id")

        # Deny denied_user object access to B (created_by is None on both, so no creator bypass).
        self._deny(self.denied_user, self.source_b)

    def _deny(self, user: User, source: ExternalDataSource) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=str(source.id),
            access_level="none",
            organization_member=membership,
        )

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

    def test_denied_user_cannot_read_source_b_via_source_id(self) -> None:
        # The resolver must filter B out of the denied user's queryset, so naming B explicitly
        # resolves to nothing and surfaces as GitHubSourceNotConnectedError -> 400 (not B's data).
        self.client.force_login(self.denied_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "GitHub" in response.json()["detail"]

    def test_denied_user_default_path_never_selects_source_b(self) -> None:
        # Make B the only otherwise-usable source by soft-deleting A, then hit the default
        # (no source_id) path. B is denied, so resolution finds nothing -> 400, not B's data.
        ExternalDataSource.objects.filter(pk=self.source_a.pk).update(deleted=True)

        self.client.force_login(self.denied_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_allowed_user_can_read_source_b_via_source_id(self) -> None:
        # Control: a user with default access resolves B fine, proving the fix denies B
        # specifically rather than blocking all access.
        self.client.force_login(self.allowed_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["truncated"] is False
