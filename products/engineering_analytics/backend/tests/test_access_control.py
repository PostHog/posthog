"""Warehouse RBAC on the engineering_analytics read endpoints, at two layers.

The curated queries run via execute_hogql_query(team=...) with no request user. Two independent
access-control layers apply, and each test class below pins one of them:

- The GitHub-source resolver honors the request user's per-source warehouse access, filtering out
  sources the user can't reach before any query runs. TestEngineeringAnalyticsAccessControl asserts
  a non-admin denied a specific source cannot read its PR/CI data -- neither by naming it via
  source_id nor by it being the default-oldest source -- while an allowed user still can. The
  curated HogQL run is stubbed to empty results so a resolved source yields 200 and a blocked source
  raises GitHubSourceNotConnectedError -> 400, isolating the resolver decision from object-storage
  availability.

- HogQL itself enforces per-object warehouse ACL once hogql-warehouse-access-control is on (#61686),
  and a userless schema build fails closed -- every warehouse table is stripped. Since the curated
  reads run with no user, that fail-closed path silently breaks the product unless a principal is
  passed. TestEngineeringAnalyticsWarehouseAclRegression guards that layer.
"""

from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from rest_framework import status

from posthog.hogql.database.database import Database

from posthog.models.organization import OrganizationMembership
from posthog.rbac.user_access_control import UserAccessControl

from products.data_warehouse.backend.tests.api._access_control_base import WarehouseAccessControlTestMixin
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    resolve_github_tables,
)
from products.engineering_analytics.backend.tests.test_views import (
    GITHUB_SOURCE_PREFIX,
    connect_github_source_without_data,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
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
    never enables the flag, so the real userless build is never exercised. This drives the real
    ``CuratedGitHubSource.run`` (built with an allowed user's access control, the way the views do),
    captures every principal it hands to ``execute_hogql_query`` -- ``user``, ``user_access_control``,
    and ``bypass_warehouse_access_control`` -- and rebuilds the schema with exactly those, so the
    assertion follows the actual curated call site no matter which principal the fix forwards. Today
    ``run`` forwards none, so the flag-on build fails closed and strips the tables; the moment the fix
    makes ``run`` forward a principal, the captured value keeps the tables and the test turns green
    (remove the xfail then). All three resolved GitHub tables (pull_requests, workflow_runs, and the
    optional workflow_jobs) are asserted, so a fix that covers only the PR/runs paths and forgets jobs
    still fails. Deterministic: ``execute_hogql_query`` is mocked and the schema build reads ORM rows
    only, so no object storage or warehouse data is needed.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="CuratedGitHubSource.run calls execute_hogql_query with no principal, so the flag-on "
        "build strips the GitHub tables. Remove this marker once run forwards a principal (request "
        "user, user_access_control, or bypass_warehouse_access_control) into execute_hogql_query.",
    )
    def test_curated_run_keeps_github_warehouse_tables_queryable(self) -> None:
        # An allowed principal: org admin short-circuits the warehouse ACL, so whichever of user /
        # user_access_control the fix forwards resolves to "allowed" rather than a coincidental default.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        user_access_control = UserAccessControl(user=self.user, team=self.team)

        # All three GitHub endpoints synced, including the optional workflow_jobs the bare helper omits.
        source = create_github_source(self.team)
        for schema in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA):
            table = create_warehouse_table_row(self.team, name=f"{GITHUB_SOURCE_PREFIX}github_{schema}", source=source)
            link_schema(self.team, source, name=schema, table=table)
        tables = resolve_github_tables(team=self.team, user_access_control=user_access_control)
        assert tables.workflow_jobs is not None  # jobs really resolved, so the assertion below bites

        # Capture every principal the real curated runner hands to HogQL, rather than hard-coding
        # them here -- so whichever one the fix forwards (user, user_access_control, or bypass), this
        # test follows it. The source is built with the UAC the views thread in.
        captured: dict = {}

        def _capture(*args, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(results=[])

        with mock.patch(
            "products.engineering_analytics.backend.logic.queries._curated.execute_hogql_query",
            side_effect=_capture,
        ):
            CuratedGitHubSource.for_team(self.team, user_access_control=user_access_control).run(
                "SELECT 1", query_type="engineering_analytics.test"
            )

        # Rebuild the schema with whatever principal run() supplied. Today it supplies none -> userless
        # -> flag-on build fails closed -> the GitHub tables are stripped.
        database = Database.create_for(
            team=self.team,
            user=captured.get("user"),
            user_access_control=captured.get("user_access_control"),
            bypass_warehouse_access_control=captured.get("bypass_warehouse_access_control", False),
        )

        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
        assert database.has_table(tables.workflow_jobs)
