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
from typing import Any

import pytest
from unittest import mock

from rest_framework import status

from posthog.hogql.database.database import Database

from posthog.rbac.user_access_control import UserAccessControl

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
from products.warehouse_sources.backend.tests.api._access_control_base import WarehouseAccessControlTestMixin

# Every curated query runs HogQL through this method; stub it to empty so a resolved source
# returns 200 with no rows, leaving the resolver's access-control decision as the only variable.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"
# The curated runner hands its assembled query to this; capture the principal it forwards.
_EXECUTE_HOGQL = "products.engineering_analytics.backend.logic.queries._curated.execute_hogql_query"
# Schema build reads this to decide whether per-table warehouse ACL is enforced.
_FLAG = "posthog.hogql.database.database.feature_enabled_or_false"


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

    def test_denied_user_cannot_write_quarantine_to_source_b(self) -> None:
        ExternalDataSource.objects.filter(pk=self.source_b.pk).update(job_inputs={"repository": "PostHog/secret"})
        github = mock.Mock()
        github.organization.return_value = "PostHog"
        github.get_default_branch.return_value = "master"
        github.get_file_contents.return_value = None
        github.create_issue.return_value = {"number": 4242, "repository": "secret"}
        github.create_branch.return_value = {"success": True, "sha": "branchsha"}
        github.update_file.return_value = {"success": True, "commit_sha": "commitsha"}
        github.create_pull_request.return_value = {
            "success": True,
            "pr_url": "https://github.com/PostHog/secret/pull/99",
        }

        self.client.force_login(self.no_access_user)
        with (
            mock.patch(
                "products.engineering_analytics.backend.logic.quarantine.GitHubIntegration", return_value=github
            ),
            mock.patch("products.engineering_analytics.backend.logic.quarantine.Integration") as integration_cls,
        ):
            integration_cls.objects.filter.return_value.first.return_value = object()
            response = self.client.post(
                self._url("quarantine/request"),
                {
                    "operation": "quarantine",
                    "selector": "posthog/api/test/test_foo.py::TestFoo::test_bar",
                    "repo": "PostHog/secret",
                    "reason": "flaky",
                    "owner": "@PostHog/team-foo",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "connected GitHub repositories" in response.json()["detail"]
        github.create_issue.assert_not_called()
        github.create_branch.assert_not_called()


@pytest.mark.ee
class TestEngineeringAnalyticsWarehouseAcl(WarehouseAccessControlTestMixin):
    """Per-table warehouse ACL on the real curated read path, once hogql-warehouse-access-control is on.

    #61686 makes a userless HogQL build fail closed -- every warehouse table is stripped from the schema
    -- which is why the curated GitHub reads (historically run with no user) 500'd when the flag rolled
    out. The fix forwards the request user into execution. These build the HogQL schema exactly as the
    runner does (capturing whatever principal ``run`` forwards, so the guard follows the fix rather than
    hard-coding it) and assert a member with default access keeps the GitHub tables, while a member
    denied the backing table loses it. Schema-build only: no object storage or warehouse rows needed.
    """

    resource = "warehouse_table"

    def setUp(self) -> None:
        super().setUp()
        self.source = create_github_source(self.team)
        self.tables = {}
        for schema in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA):
            table = create_warehouse_table_row(
                self.team, name=f"{GITHUB_SOURCE_PREFIX}github_{schema}", source=self.source
            )
            link_schema(self.team, self.source, name=schema, table=table)
            self.tables[schema] = table

    def _schema_as_runner_builds_it(self, user_access_control: UserAccessControl | None) -> tuple[Database, dict]:
        # Capture the principal the real curated runner forwards for this access control, then rebuild the
        # schema with it under the flag -- so this follows whatever run() passes (user / access control /
        # bypass), not a hard-coded shape. Returns the schema and the captured kwargs.
        captured: dict = {}

        def _capture(*_args: Any, **kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(results=[])

        with mock.patch(_EXECUTE_HOGQL, side_effect=_capture):
            CuratedGitHubSource.for_team(self.team, user_access_control=user_access_control).run(
                "SELECT 1", query_type="engineering_analytics.test"
            )

        def _flag_enabled(key: str, *_args: Any, **_kwargs: Any) -> bool:
            return key == "hogql-warehouse-access-control"

        with mock.patch(_FLAG, side_effect=_flag_enabled):
            database = Database.create_for(
                team=self.team,
                user=captured.get("user"),
                user_access_control=captured.get("user_access_control"),
                bypass_warehouse_access_control=captured.get("bypass_warehouse_access_control", False),
            )
        return database, captured

    def test_member_with_default_access_keeps_github_tables(self) -> None:
        # A normal member (no explicit restriction) defaults to editor on the warehouse tables, so the
        # forwarded user keeps all three GitHub tables in the schema -- the read works under the flag.
        uac = UserAccessControl(self.editor_user, self.team)
        tables = resolve_github_tables(team=self.team, user_access_control=uac)
        database, _ = self._schema_as_runner_builds_it(uac)

        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
        assert tables.workflow_jobs is not None and database.has_table(tables.workflow_jobs)

    def test_member_denied_backing_table_cannot_query_it(self) -> None:
        # Deny one member the workflow_runs table specifically. Forwarding the user now honors that: the
        # denied table is stripped (so reads of it are blocked, not silently returned), while an
        # un-denied sibling stays queryable -- the security win the bypass gave up.
        self._create_access_control(
            self.no_access_user,
            resource="warehouse_table",
            resource_id=str(self.tables[WORKFLOW_RUNS_SCHEMA].id),
            access_level="none",
        )
        uac = UserAccessControl(self.no_access_user, self.team)
        tables = resolve_github_tables(team=self.team, user_access_control=uac)
        database, _ = self._schema_as_runner_builds_it(uac)

        assert not database.has_table(tables.workflow_runs)
        assert database.has_table(tables.pull_requests)

    def test_userless_system_read_bypasses_acl_and_keeps_tables(self) -> None:
        # The facade documents a userless path (user_access_control=None) for system / Temporal / CLI
        # callers. There is no principal to honor the table ACL with, so the runner bypasses it rather
        # than fail closed and strip the tables under the flag.
        tables = resolve_github_tables(team=self.team)
        database, captured = self._schema_as_runner_builds_it(None)

        assert captured.get("bypass_warehouse_access_control") is True
        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
        assert tables.workflow_jobs is not None and database.has_table(tables.workflow_jobs)
