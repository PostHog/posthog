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
from posthog.test.base import BaseTest
from unittest import mock

from rest_framework import status

from posthog.hogql.database.database import Database

from products.data_warehouse.backend.tests.api._access_control_base import WarehouseAccessControlTestMixin
from products.engineering_analytics.backend.tests.test_views import connect_github_source_without_data
from products.warehouse_sources.backend.facade.models import ExternalDataSource

# Every curated query runs HogQL through this method; stub it to empty so a resolved source
# returns 200 with no rows, leaving the resolver's access-control decision as the only variable.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"


@pytest.mark.ee
class TestEngineeringAnalyticsAccessControl(WarehouseAccessControlTestMixin):
    """A team with two connected GitHub sources, A (oldest) and B. ``no_access_user`` is denied
    object access to B; ``editor_user`` keeps default access."""

    resource = "external_data_source"

    def setUp(self) -> None:
        super().setUp()
        # Two usable GitHub sources (both endpoints synced over ORM-only tables, no object storage).
        # A is created first, so the default-oldest path selects A.
        connect_github_source_without_data(self.team, prefix="sourcea")
        connect_github_source_without_data(self.team, prefix="sourceb")
        self.source_a, self.source_b = ExternalDataSource.objects.order_by("created_at", "id")
        # created_by is None on both seed sources, so no creator bypass of the deny.
        self._create_access_control(self.no_access_user, resource_id=str(self.source_b.id), access_level="none")

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

    def test_denied_user_cannot_read_source_b_via_source_id(self) -> None:
        # The resolver must filter B out of the denied user's queryset, so naming B explicitly
        # resolves to nothing and surfaces as GitHubSourceNotConnectedError -> 400 (not B's data).
        self.client.force_login(self.no_access_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "GitHub" in response.json()["detail"]

    def test_denied_user_default_path_never_selects_source_b(self) -> None:
        # Make B the only otherwise-usable source by soft-deleting A, then hit the default
        # (no source_id) path. B is denied, so resolution finds nothing -> 400, not B's data.
        ExternalDataSource.objects.filter(pk=self.source_a.pk).update(deleted=True)

        self.client.force_login(self.no_access_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_allowed_user_can_read_source_b_via_source_id(self) -> None:
        # Control: a user with default access resolves B fine, proving the fix denies B
        # specifically rather than blocking all access.
        self.client.force_login(self.editor_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["truncated"] is False

    def test_denied_user_cannot_enumerate_source_b_via_sources(self) -> None:
        # The picker lists only sources the user can access; B is denied, so it must not appear --
        # no id/repo/prefix enumeration of a restricted source, and no source_id to feed the reads.
        self.client.force_login(self.no_access_user)
        response = self.client.get(self._url("sources"))

        assert response.status_code == status.HTTP_200_OK
        ids = {source["id"] for source in response.json()}
        assert str(self.source_a.id) in ids
        assert str(self.source_b.id) not in ids

    def test_allowed_user_can_enumerate_source_b_via_sources(self) -> None:
        self.client.force_login(self.editor_user)
        response = self.client.get(self._url("sources"))

        assert response.status_code == status.HTTP_200_OK
        assert str(self.source_b.id) in {source["id"] for source in response.json()}


@mock.patch("posthoganalytics.feature_enabled", new=mock.Mock(return_value=True))
class TestEngineeringAnalyticsWarehouseAclRegression(BaseTest):
    """Regression guard for the userless warehouse read path (HogQL warehouse access control, #61686).

    The curated queries run through ``CuratedGitHubSource.run`` ->
    ``execute_hogql_query(team=..., query_type=...)`` with no request user and no
    ``bypass_warehouse_access_control``. With the ``hogql-warehouse-access-control`` flag on, a
    userless ``Database`` fails closed: every warehouse table is stripped from the schema, so the
    curated GitHub tables become unqueryable and every read endpoint raises
    ``You don't have access to table`` -> 500.

    The rest of this product's suite missed this because it stubs ``CuratedGitHubSource.run`` and
    never enables the flag, so the real userless build is never exercised. This builds the database
    exactly as the product does -- team-scoped, no user -- with the flag on and asserts the resolved
    GitHub warehouse tables stay in the schema. Deterministic: the deny decision happens at
    schema-build time, before any object-storage read, so no warehouse data is needed.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="Curated reads run userless without bypass_warehouse_access_control, so the flag-on "
        "build strips the GitHub tables. Remove this marker once engineering_analytics passes a "
        "principal (request user or bypass_warehouse_access_control) into execute_hogql_query.",
    )
    def test_userless_curated_build_keeps_github_warehouse_tables(self) -> None:
        tables = connect_github_source_without_data(self.team)

        # Mirrors execute_hogql_query(team=..., query_type=...): team-scoped, no user, no bypass.
        database = Database.create_for(team=self.team, user=None)

        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
