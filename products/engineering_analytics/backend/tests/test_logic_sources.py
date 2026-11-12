from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import GitHubSource, GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    ISSUE_EVENTS_SCHEMA,
    PULL_REQUESTS_SCHEMA,
    TEAM_MEMBERS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
    JobSourceTables,
    TeamMembershipTable,
    list_github_sources,
    resolve_ci_data_freshness,
    resolve_github_tables,
    resolve_job_source_tables,
    resolve_team_membership_table,
)
from products.engineering_analytics.backend.logic.views.depot_ci import DepotJobAttempts
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    create_depot_source,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests._logic_helpers import _ago, _WarehouseMixin
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

_SYNCED_AT = datetime(2026, 3, 2, 12, tzinfo=UTC)


class TestResolveGitHubTables(BaseTest):
    def _connect(
        self,
        *,
        prefix: str,
        schemas: list[tuple[str, bool, bool]],
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
        team: Team | None = None,
        repository: str = "",
    ) -> ExternalDataSource:
        # schemas: (endpoint name, should_sync, has a backing table)
        team = team or self.team
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
            job_inputs={"repository": repository} if repository else None,
        )
        for name, should_sync, has_table in schemas:
            table = (
                create_warehouse_table_row(team, name=f"{prefix}github_{name}", source=source) if has_table else None
            )
            link_schema(team, source, name=name, table=table, should_sync=should_sync)
        return source

    _BOTH_SYNCED = [(PULL_REQUESTS_SCHEMA, True, True), (WORKFLOW_RUNS_SCHEMA, True, True)]

    def test_resolves_non_default_prefix_tables(self) -> None:
        source = self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="myprefixgithub_pull_requests",
            workflow_runs="myprefixgithub_workflow_runs",
            source_id=str(source.id),
        )

    @parameterized.expand([("with_team_requests", ["event", "requested_team"], True), ("without", ["event"], False)])
    def test_flags_issue_events_that_hold_team_review_requests(
        self, _name: str, columns: list[str], expected: bool
    ) -> None:
        source = self._connect(prefix="flag", schemas=self._BOTH_SYNCED)
        table = create_warehouse_table_row(self.team, name="flaggithub_issue_events", source=source)
        table.columns = {
            column: {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"} for column in columns
        }
        table.save()
        link_schema(self.team, source, name=ISSUE_EVENTS_SCHEMA, table=table, should_sync=True)

        tables = resolve_github_tables(team=self.team)

        assert (tables.issue_events, tables.issue_events_team_requests) == ("flaggithub_issue_events", expected)

    @parameterized.expand(
        [
            ("github_only", None, False, _SYNCED_AT),
            ("depot_synced_earlier", _SYNCED_AT - timedelta(hours=2), True, _SYNCED_AT - timedelta(hours=2)),
            ("depot_synced_later", _SYNCED_AT + timedelta(hours=2), True, _SYNCED_AT),
            ("depot_never_synced", None, True, None),
        ]
    )
    def test_ci_data_freshness_is_the_older_of_the_github_and_depot_syncs(
        self, _name: str, depot_synced_at: datetime | None, has_depot: bool, expected: datetime | None
    ) -> None:
        source = self._connect(
            prefix="fresh",
            schemas=[*self._BOTH_SYNCED, (WORKFLOW_JOBS_SCHEMA, True, True)],
            repository="PostHog/posthog",
        )
        ExternalDataSchema.objects.filter(source=source).update(last_synced_at=_SYNCED_AT)
        if has_depot:
            depot = create_depot_source(self.team, prefix="ci", repository="posthog/PostHog")
            schema = link_schema(
                self.team,
                depot,
                name=DEPOT_JOB_ATTEMPTS_SCHEMA,
                table=create_warehouse_table_row(self.team, name="cidepot_job_attempts", source=depot),
            )
            ExternalDataSchema.objects.filter(id=schema.id).update(last_synced_at=depot_synced_at)

        freshness = resolve_ci_data_freshness(team=self.team, tables=resolve_github_tables(team=self.team))

        assert (freshness.runs_synced_at, freshness.jobs_synced_at) == (expected, expected)

    @parameterized.expand(
        [
            ("with_roles", ["login", "team_slug", "role"], True),
            ("without_roles", ["login", "team_slug"], False),
        ]
    )
    def test_resolves_membership_snapshot_without_the_pull_request_endpoints(
        self, _name: str, columns: list[str], expected_roles: bool
    ) -> None:
        source = self._connect(prefix="roster", schemas=[])
        table = create_warehouse_table_row(self.team, name="rostergithub_team_members", source=source)
        table.columns = {
            column: {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"} for column in columns
        }
        table.save()
        link_schema(self.team, source, name=TEAM_MEMBERS_SCHEMA, table=table, should_sync=True)

        assert resolve_team_membership_table(team=self.team) == TeamMembershipTable(
            table="rostergithub_team_members", has_role=expected_roles
        )

    def test_resolves_no_membership_snapshot_when_the_endpoint_is_unsynced(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        assert resolve_team_membership_table(team=self.team) is None

    def test_repo_scoped_resolution_survives_non_dict_job_inputs(self) -> None:
        # job_inputs is an EncryptedJSONField, so it can hold any JSON value.
        source = self._connect(prefix="weird", schemas=self._BOTH_SYNCED)
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=["not", "a", "dict"])
        tables = resolve_github_tables(team=self.team, repo="PostHog/posthog")
        assert tables.pull_requests == "weirdgithub_pull_requests"

    def test_raises_without_a_github_source(self) -> None:
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_build_raises_without_a_github_source(self) -> None:
        with self.assertRaises(GitHubSourceNotConnectedError):
            api.get_ci_cards(team=self.team)

    @parameterized.expand(
        [
            ("non_github_source", [(PULL_REQUESTS_SCHEMA, True, True), (WORKFLOW_RUNS_SCHEMA, True, True)], "stripe"),
            ("endpoint_not_synced", [(PULL_REQUESTS_SCHEMA, False, True), (WORKFLOW_RUNS_SCHEMA, False, True)], "gh"),
            ("missing_one_endpoint", [(PULL_REQUESTS_SCHEMA, True, True)], "gh"),
            ("schema_without_table", [(PULL_REQUESTS_SCHEMA, True, False), (WORKFLOW_RUNS_SCHEMA, True, False)], "gh"),
        ]
    )
    def test_raises_when_endpoints_unavailable(
        self, _name: str, schemas: list[tuple[str, bool, bool]], kind: str
    ) -> None:
        source_type = ExternalDataSourceType.STRIPE if kind == "stripe" else ExternalDataSourceType.GITHUB
        self._connect(prefix="myprefix", schemas=schemas, source_type=source_type)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_prefers_oldest_complete_source(self) -> None:
        self._connect(prefix="older", schemas=self._BOTH_SYNCED)
        self._connect(prefix="newer", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables.pull_requests == "oldergithub_pull_requests"

    @parameterized.expand(
        [
            ("listed_source_connected", True, "livegithub_pull_requests"),
            ("fallback", False, "stalegithub_pull_requests"),
        ]
    )
    def test_default_prefers_the_source_the_list_reports_as_synced(
        self, _name: str, connect_live: bool, expected_table: str
    ) -> None:
        # The older source lists the repo but holds its tables as unattributed bare rows, so the list
        # reports it as not synced although its tables still resolve.
        stale = self._connect(prefix="stale", schemas=self._BOTH_SYNCED)
        ExternalDataSource.objects.filter(pk=stale.pk).update(job_inputs={"repositories": ["PostHog/posthog"]})
        if connect_live:
            self._connect(prefix="live", schemas=self._BOTH_SYNCED, repository="PostHog/posthog")

        listed = {entry.prefix: entry.synced for entry in list_github_sources(team=self.team)}
        tables = resolve_github_tables(team=self.team)

        assert listed["stale"] is False
        assert tables.pull_requests == expected_table

    def test_skips_incomplete_source_for_a_complete_one(self) -> None:
        self._connect(prefix="incomplete", schemas=[(PULL_REQUESTS_SCHEMA, True, True)])
        complete = self._connect(prefix="complete", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="completegithub_pull_requests",
            workflow_runs="completegithub_workflow_runs",
            source_id=str(complete.id),
        )

    def test_ignores_soft_deleted_source(self) -> None:
        source = self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        ExternalDataSource.objects.filter(pk=source.pk).update(deleted=True)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_source_id_selects_a_specific_source(self) -> None:
        self._connect(prefix="older", schemas=self._BOTH_SYNCED)
        newer = self._connect(prefix="newer", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team, source_id=str(newer.id))
        assert tables == GitHubTables(
            pull_requests="newergithub_pull_requests",
            workflow_runs="newergithub_workflow_runs",
            source_id=str(newer.id),
        )

    def test_unknown_source_id_raises(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id="0192f000-0000-7000-8000-000000000000")

    def test_malformed_source_id_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_github_tables(team=self.team, source_id="not-a-uuid")

    def test_source_id_is_scoped_to_the_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_source = self._connect(prefix="other", schemas=self._BOTH_SYNCED, team=other_team)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id=str(other_source.id))


class TestListGitHubSources(BaseTest):
    def _source(
        self,
        *,
        prefix: str,
        repository: str | None = None,
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
        team: Team | None = None,
    ) -> ExternalDataSource:
        team = team or self.team
        return ExternalDataSource.objects.create(
            team=team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
            job_inputs={"repository": repository} if repository else {},
        )

    def test_lists_sources_oldest_first_with_repo_and_prefix(self) -> None:
        older = self._source(prefix="older", repository="PostHog/posthog")
        newer = self._source(prefix="newer", repository="PostHog/posthog.com")
        assert list_github_sources(team=self.team) == [
            GitHubSource(id=str(older.id), repo="PostHog/posthog", prefix="older"),
            GitHubSource(id=str(newer.id), repo="PostHog/posthog.com", prefix="newer"),
        ]

    def test_includes_sources_without_synced_tables(self) -> None:
        source = self._source(prefix="pronly", repository="PostHog/posthog")
        assert [s.id for s in list_github_sources(team=self.team)] == [str(source.id)]

    def test_repo_is_blank_without_a_repository_input(self) -> None:
        source = self._source(prefix="noinputs")
        assert list_github_sources(team=self.team) == [GitHubSource(id=str(source.id), repo="", prefix="noinputs")]

    def test_repo_is_blank_when_job_inputs_is_not_a_dict(self) -> None:
        source = self._source(prefix="weird")
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=["not", "a", "dict"])
        assert list_github_sources(team=self.team) == [GitHubSource(id=str(source.id), repo="", prefix="weird")]

    def test_empty_repositories_list_falls_back_to_legacy_repository(self) -> None:
        # The sync parser treats an empty `repositories` list as unset and syncs the legacy repo.
        source = self._source(prefix="emptylist", repository="PostHog/posthog")
        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={"repository": "PostHog/posthog", "repositories": []}
        )
        assert list_github_sources(team=self.team) == [
            GitHubSource(id=str(source.id), repo="PostHog/posthog", prefix="emptylist")
        ]

    def test_excludes_non_github_and_soft_deleted_sources(self) -> None:
        self._source(prefix="stripe", source_type=ExternalDataSourceType.STRIPE)
        deleted = self._source(prefix="gone", repository="PostHog/posthog")
        ExternalDataSource.objects.filter(pk=deleted.pk).update(deleted=True)
        kept = self._source(prefix="kept", repository="PostHog/posthog")
        assert [s.id for s in list_github_sources(team=self.team)] == [str(kept.id)]

    def test_empty_without_a_github_source(self) -> None:
        assert list_github_sources(team=self.team) == []

    def test_scoped_to_the_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._source(prefix="theirs", repository="PostHog/posthog", team=other_team)
        assert list_github_sources(team=self.team) == []


class TestMultiRepoGitHubResolution(BaseTest):
    @staticmethod
    def _slug(repo: str) -> str:
        return repo.replace("/", "_").replace(".", "_").lower()

    def _multi_repo_source(
        self,
        *,
        prefix: str,
        legacy_repository: str = "",
        repos: dict[str, list[tuple[str, bool]]],
    ) -> ExternalDataSource:
        # repos: {repo_full_name: [(endpoint, has_table), ...]}. The repo equal to legacy_repository
        # keeps bare endpoint names. Every other repo is named `owner/repo.endpoint` with location
        # metadata, as the multi-repo GitHub source lands them.
        job_inputs: dict[str, Any] = {"repositories": list(repos.keys())}
        if legacy_repository:
            job_inputs["repository"] = legacy_repository
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"src-{prefix}",
            connection_id=f"src-{prefix}",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=prefix,
            job_inputs=job_inputs,
        )
        for repo, endpoints in repos.items():
            is_legacy = bool(legacy_repository) and repo.casefold() == legacy_repository.casefold()
            for endpoint, has_table in endpoints:
                name = endpoint if is_legacy else f"{repo}.{endpoint}"
                table = (
                    create_warehouse_table_row(
                        self.team, name=f"{prefix}github_{self._slug(repo)}_{endpoint}", source=source
                    )
                    if has_table
                    else None
                )
                ExternalDataSchema.objects.create(
                    team=self.team,
                    source=source,
                    name=name,
                    table=table,
                    should_sync=True,
                    sync_type_config={}
                    if is_legacy
                    else {"schema_metadata": {"source_repository": repo.lower(), "source_endpoint": endpoint}},
                )
        return source

    def test_new_source_single_qualified_repo_resolves(self) -> None:
        source = self._multi_repo_source(
            prefix="fresh",
            repos={"PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)]},
        )
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="freshgithub_posthog_posthog_pull_requests",
            workflow_runs="freshgithub_posthog_posthog_workflow_runs",
            repository="posthog/posthog",
            source_id=str(source.id),
        )

    @parameterized.expand(
        [
            (None, "PostHog/posthog", "mixgithub_posthog_posthog_pull_requests"),
            ("posthog/posthog.com", "posthog/posthog.com", "mixgithub_posthog_posthog_com_pull_requests"),
            ("POSTHOG/POSTHOG", "PostHog/posthog", "mixgithub_posthog_posthog_pull_requests"),
        ]
    )
    def test_multi_repo_source_scopes_by_repo(self, repo: str | None, expected_repo: str, expected_pr: str) -> None:
        self._multi_repo_source(
            prefix="mix",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        tables = resolve_github_tables(team=self.team, repo=repo)
        assert tables.repository == expected_repo
        assert tables.pull_requests == expected_pr

    def test_picker_marks_repos_with_both_endpoints_synced(self) -> None:
        self._multi_repo_source(
            prefix="mark",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True)],
            },
        )
        assert {source.repo: source.synced for source in list_github_sources(team=self.team)} == {
            "PostHog/posthog": True,
            "posthog/posthog.com": False,
        }

    def test_default_repo_follows_configured_order_not_alphabetical(self) -> None:
        self._multi_repo_source(
            prefix="ordered",
            repos={
                "z/org": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "a/org": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        # _multi_repo_source stores repositories in dict order, so z/org is configured first.
        assert resolve_github_tables(team=self.team).repository == "z/org"

    def test_default_follows_configured_order_even_over_the_legacy_repo(self) -> None:
        self._multi_repo_source(
            prefix="legacyorder",
            legacy_repository="PostHog/posthog",
            repos={
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        assert resolve_github_tables(team=self.team).repository == "posthog/posthog.com"

    def test_explicit_repo_does_not_fall_through_to_a_sibling_repo(self) -> None:
        self._multi_repo_source(
            prefix="partial",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True)],
            },
        )
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, repo="posthog/posthog.com")
        assert resolve_github_tables(team=self.team, repo="PostHog/posthog").repository == "PostHog/posthog"

    def test_incomplete_exact_match_does_not_fall_through_to_a_bare_source(self) -> None:
        self._multi_repo_source(
            prefix="halfsynced",
            repos={"posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True)]},
        )
        bare = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src-bare",
            connection_id="src-bare",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="bare",
            job_inputs={},
        )
        for endpoint in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA):
            ExternalDataSchema.objects.create(
                team=self.team,
                source=bare,
                name=endpoint,
                table=create_warehouse_table_row(self.team, name=f"baregithub_{endpoint}", source=bare),
                should_sync=True,
                sync_type_config={},
            )
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, repo="posthog/posthog.com")
        # A repo with no candidate of its own falls back to the bare rows.
        assert resolve_github_tables(team=self.team, repo="some/other").pull_requests == "baregithub_pull_requests"

    def test_cost_pairs_include_every_repo_in_a_source(self) -> None:
        source = self._multi_repo_source(
            prefix="cost",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(WORKFLOW_RUNS_SCHEMA, True), (WORKFLOW_JOBS_SCHEMA, True)],
                "posthog/posthog.com": [(WORKFLOW_RUNS_SCHEMA, True), (WORKFLOW_JOBS_SCHEMA, True)],
                # This repo has no jobs table, so it is excluded.
                "posthog/other": [(WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        with_prs = self._multi_repo_source(
            prefix="prs",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [
                    (WORKFLOW_RUNS_SCHEMA, True),
                    (WORKFLOW_JOBS_SCHEMA, True),
                    (PULL_REQUESTS_SCHEMA, True),
                ]
            },
        )
        # The Depot source attaches to one entry for its repository: the entry that has the PR snapshot.
        depot = create_depot_source(self.team, prefix="ci", repository="posthog/PostHog")
        link_schema(
            self.team,
            depot,
            name=DEPOT_JOB_ATTEMPTS_SCHEMA,
            table=create_warehouse_table_row(self.team, name="cidepot_job_attempts", source=depot),
        )
        assert set(resolve_job_source_tables(self.team)) == {
            JobSourceTables(
                github_workflow_jobs="costgithub_posthog_posthog_workflow_jobs",
                github_workflow_runs="costgithub_posthog_posthog_workflow_runs",
                pull_requests=None,
                source_id=str(source.id),
                repository="posthog/posthog",
            ),
            JobSourceTables(
                github_workflow_jobs="prsgithub_posthog_posthog_workflow_jobs",
                github_workflow_runs="prsgithub_posthog_posthog_workflow_runs",
                pull_requests="prsgithub_posthog_posthog_pull_requests",
                source_id=str(with_prs.id),
                repository="posthog/posthog",
                depot_job_attempts=DepotJobAttempts(table="cidepot_job_attempts", repository="posthog/posthog"),
            ),
            JobSourceTables(
                github_workflow_jobs="costgithub_posthog_posthog_com_workflow_jobs",
                github_workflow_runs="costgithub_posthog_posthog_com_workflow_runs",
                pull_requests=None,
                source_id=str(source.id),
                repository="posthog/posthog.com",
            ),
        }

    def test_picker_lists_one_entry_per_configured_repo(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src-picker",
            connection_id="src-picker",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="picker",
            job_inputs={"repository": "PostHog/posthog", "repositories": ["PostHog/posthog", "PostHog/posthog.com"]},
        )
        assert list_github_sources(team=self.team) == [
            GitHubSource(id=str(source.id), repo="PostHog/posthog", prefix="picker"),
            GitHubSource(id=str(source.id), repo="PostHog/posthog.com", prefix="picker"),
        ]


class TestMultiSourceResolutionWarehouse(_WarehouseMixin, BaseTest):
    def _connect_source(self, *, source_id: str, prefix: str, repository: str) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=source_id,
            connection_id=source_id,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=prefix,
            job_inputs={"repository": repository},
        )

    def test_resolve_branch_targets_the_repo_scoped_source(self) -> None:
        older = self._connect_source(source_id="src-a", prefix="repoa", repository="PostHog/posthog")
        newer = self._connect_source(source_id="src-b", prefix="repob", repository="PostHog/posthog.com")
        self._create_table("github_pull_requests", PULL_REQUESTS_COLUMNS, [], source=older, prefix="repoa")
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [], source=older, prefix="repoa")
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    61,
                    "alice",
                    "open",
                    0,
                    _ago(2),
                    head_sha="sha61",
                    head_ref="feat/login",
                    full_name="PostHog/posthog.com",
                )
            ],
            source=newer,
            prefix="repob",
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [], source=newer, prefix="repob")

        # The repo argument differs in case from the source's repository on purpose.
        matches = api.resolve_branch(team=self.team, branch="feat/login", repo="posthog/POSTHOG.com")
        assert [(m.repo, m.number) for m in matches] == [("PostHog/posthog.com", 61)]
        # Without the repo hint the older source is searched, and it does not hold the PR.
        assert api.resolve_branch(team=self.team, branch="feat/login") == []
