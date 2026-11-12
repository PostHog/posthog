from types import SimpleNamespace
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.database.database import Database

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    resolve_github_tables,
)
from products.engineering_analytics.backend.logic.views import ci_rows
from products.engineering_analytics.backend.tests._github_fixtures import (
    GITHUB_SOURCE_PREFIX,
    connect_github_source_without_data,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests.test_materialized_ci import _covered_since, _ready_views
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin

# Stubbed to empty results so that a resolved source returns 200 and a blocked source returns 400.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"
_EXECUTE_HOGQL = "products.engineering_analytics.backend.logic.queries._curated.execute_hogql_query"
# The schema build reads this flag to decide whether per-table warehouse access control applies.
_FLAG = "posthog.hogql.database.database.feature_enabled_or_false"


@pytest.mark.ee
class TestEngineeringAnalyticsAccessControl(WarehouseAccessControlTestMixin):
    resource = "external_data_source"

    def setUp(self) -> None:
        super().setUp()
        # A is created first, so the default path selects A.
        connect_github_source_without_data(self.team, prefix="sourcea")
        connect_github_source_without_data(self.team, prefix="sourceb")
        self.source_a, self.source_b = ExternalDataSource.objects.order_by("created_at", "id")
        # created_by is None on both sources, so the creator bypass does not apply to the deny.
        self._create_access_control(self.no_access_user, resource_id=str(self.source_b.id), access_level="none")

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

    def test_denied_user_cannot_read_source_b_via_source_id(self) -> None:
        self.client.force_login(self.no_access_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "GitHub" in response.json()["detail"]

    def test_denied_user_default_path_never_selects_source_b(self) -> None:
        # With A soft-deleted, B is the only source left for the default path.
        ExternalDataSource.objects.filter(pk=self.source_a.pk).update(deleted=True)

        self.client.force_login(self.no_access_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_allowed_user_can_read_source_b_via_source_id(self) -> None:
        self.client.force_login(self.editor_user)
        with mock.patch(_RUN_QUERY, return_value=SimpleNamespace(results=[])):
            response = self.client.get(self._url("pull_requests"), {"source_id": str(self.source_b.id)})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["truncated"] is False

    def test_denied_user_cannot_enumerate_source_b_via_sources(self) -> None:
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
            mock.patch("products.engineering_analytics.backend.logic.quarantine.IntegrationManager") as manager,
        ):
            manager.github.oauth.find.return_value = object()
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
        # The schema is built from the kwargs that run() passes to execute_hogql_query, so the tests
        # follow the principal the runner forwards.
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
        uac = UserAccessControl(self.editor_user, self.team)
        tables = resolve_github_tables(team=self.team, user_access_control=uac)
        database, _ = self._schema_as_runner_builds_it(uac)

        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
        assert tables.workflow_jobs is not None and database.has_table(tables.workflow_jobs)

    def test_member_denied_backing_table_cannot_query_it(self) -> None:
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
        # System callers pass user_access_control=None. No principal exists to check, so the runner
        # bypasses the table access control.
        tables = resolve_github_tables(team=self.team)
        database, captured = self._schema_as_runner_builds_it(None)

        assert captured.get("bypass_warehouse_access_control") is True
        assert database.has_table(tables.pull_requests)
        assert database.has_table(tables.workflow_runs)
        assert tables.workflow_jobs is not None and database.has_table(tables.workflow_jobs)

    @parameterized.expand(["allowed", "raw_table_denied", "stored_view_denied"])
    def test_materialized_reads_preserve_raw_and_view_permissions(self, condition: str) -> None:
        views = _ready_views(self)
        if condition != "allowed":
            self._create_access_control(
                self.no_access_user,
                resource="warehouse_table" if condition == "raw_table_denied" else "warehouse_view",
                resource_id=str(self.tables[WORKFLOW_RUNS_SCHEMA].id)
                if condition == "raw_table_denied"
                else str(views[ci_rows.RUNS_VIEW_NAME].id),
                access_level="none",
            )
        with (
            mock.patch("posthoganalytics.feature_enabled", return_value=True),
            mock.patch(_FLAG, return_value=True),
        ):
            reader = CuratedGitHubSource.for_team(
                self.team, user_access_control=UserAccessControl(self.no_access_user, self.team)
            )
            source = reader.run_source(since=_covered_since())
            if condition == "allowed":
                assert ci_rows.RUNS_VIEW_NAME in source
            else:
                assert ci_rows.RUNS_VIEW_NAME not in source
            assert reader.may_read_ci_tables() is (condition != "raw_table_denied")
