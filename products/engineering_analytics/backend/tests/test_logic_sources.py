from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import GitHubSource, GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
    list_github_sources,
    resolve_github_tables,
    resolve_job_cost_source_pairs,
)
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests._logic_helpers import _ago, _WarehouseMixin
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestResolveGitHubTables(BaseTest):
    """The per-team table resolver over the warehouse models (ORM only, no object storage).
    No source is connected in setUp so the missing-source path can be exercised."""

    def _connect(
        self,
        *,
        prefix: str,
        schemas: list[tuple[str, bool, bool]],
        source_type: ExternalDataSourceType = ExternalDataSourceType.GITHUB,
        team: Team | None = None,
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
        )
        for name, should_sync, has_table in schemas:
            table = (
                create_warehouse_table_row(team, name=f"{prefix}github_{name}", source=source) if has_table else None
            )
            link_schema(team, source, name=name, table=table, should_sync=should_sync)
        return source

    _BOTH_SYNCED = [(PULL_REQUESTS_SCHEMA, True, True), (WORKFLOW_RUNS_SCHEMA, True, True)]

    def test_resolves_non_default_prefix_tables(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="myprefixgithub_pull_requests", workflow_runs="myprefixgithub_workflow_runs"
        )

    def test_repo_scoped_resolution_survives_non_dict_job_inputs(self) -> None:
        # job_inputs is an EncryptedJSONField that can hold any JSON value; the repo-first ordering
        # must treat a non-dict as "no repository input", not crash the whole resolution.
        source = self._connect(prefix="weird", schemas=self._BOTH_SYNCED)
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=["not", "a", "dict"])
        tables = resolve_github_tables(team=self.team, repo="PostHog/posthog")
        assert tables.pull_requests == "weirdgithub_pull_requests"

    def test_raises_without_a_github_source(self) -> None:
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team)

    def test_build_raises_without_a_github_source(self) -> None:
        # The orchestrator surfaces the resolver's error so the viewset can map it to a 400.
        with self.assertRaises(GitHubSourceNotConnectedError):
            api.get_ci_cards(team=self.team)

    @parameterized.expand(
        [
            # Same-named schemas on a non-GitHub source must not be mistaken for a GitHub source.
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
        # Two fully-connected GitHub sources (e.g. one per repo): the oldest wins, deterministically.
        self._connect(prefix="older", schemas=self._BOTH_SYNCED)
        self._connect(prefix="newer", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables.pull_requests == "oldergithub_pull_requests"

    def test_skips_incomplete_source_for_a_complete_one(self) -> None:
        # The oldest source is missing an endpoint; resolution falls through to the complete one.
        self._connect(prefix="incomplete", schemas=[(PULL_REQUESTS_SCHEMA, True, True)])
        self._connect(prefix="complete", schemas=self._BOTH_SYNCED)
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="completegithub_pull_requests", workflow_runs="completegithub_workflow_runs"
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
            pull_requests="newergithub_pull_requests", workflow_runs="newergithub_workflow_runs"
        )

    def test_unknown_source_id_raises(self) -> None:
        self._connect(prefix="myprefix", schemas=self._BOTH_SYNCED)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id="0192f000-0000-7000-8000-000000000000")

    def test_malformed_source_id_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_github_tables(team=self.team, source_id="not-a-uuid")

    def test_source_id_is_scoped_to_the_team(self) -> None:
        # Selecting another team's source id must not leak it — the team filter excludes it.
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_source = self._connect(prefix="other", schemas=self._BOTH_SYNCED, team=other_team)
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, source_id=str(other_source.id))


class TestListGitHubSources(BaseTest):
    """list_github_sources lists every connected GitHub source for a picker (ORM only).
    Unlike resolve_github_tables it does not require synced tables — a half-synced source the
    user connected should still be selectable; the empty state handles an unusable pick."""

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
        # No schemas/tables linked: resolve_github_tables would reject this, the picker keeps it.
        source = self._source(prefix="pronly", repository="PostHog/posthog")
        assert [s.id for s in list_github_sources(team=self.team)] == [str(source.id)]

    def test_repo_is_blank_without_a_repository_input(self) -> None:
        source = self._source(prefix="noinputs")
        assert list_github_sources(team=self.team) == [GitHubSource(id=str(source.id), repo="", prefix="noinputs")]

    def test_repo_is_blank_when_job_inputs_is_not_a_dict(self) -> None:
        # job_inputs is an EncryptedJSONField that can hold any JSON value; a non-dict must not crash
        # the shared repository read (it backs every endpoint via resolve_github_tables), just yield "".
        source = self._source(prefix="weird")
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=["not", "a", "dict"])
        assert list_github_sources(team=self.team) == [GitHubSource(id=str(source.id), repo="", prefix="weird")]

    def test_empty_repositories_list_falls_back_to_legacy_repository(self) -> None:
        # A legacy source with `repository` set but `repositories: []` (empty) — the sync parser treats
        # the empty list as unset and still syncs the legacy repo, so the picker must list that repo, not
        # a blank unknown entry.
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
    """One GitHub source can sync several repositories: its added repos carry repo-qualified schema
    rows (``owner/repo.endpoint`` + location metadata) while its original repo keeps bare names.
    These guard the regression where the resolver only matched bare endpoint names — which made
    every repo-qualified row (including a new source's single day-one-qualified repo) invisible, so
    the product 400'd, and silently dropped a multi-repo source's added repos from the cost view."""

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
        # repos: {repo_full_name: [(endpoint, has_table), ...]}. The repo equal to
        # legacy_repository keeps bare endpoint names (the source's pre-multi-repo repo); every
        # other repo is qualified as ``owner/repo.endpoint`` with location metadata, exactly as the
        # multi-repo GitHub source lands them.
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
        # A source created via the multi-repo `repositories` field has no legacy `repository`, so its
        # one repo is qualified from day one. Bare-name matching would 400 this — the onboarding break.
        self._multi_repo_source(
            prefix="fresh",
            repos={"PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)]},
        )
        tables = resolve_github_tables(team=self.team)
        assert tables == GitHubTables(
            pull_requests="freshgithub_posthog_posthog_pull_requests",
            workflow_runs="freshgithub_posthog_posthog_workflow_runs",
            repository="posthog/posthog",
        )

    @parameterized.expand(
        [
            # (repo arg, expected resolved repo, expected pull_requests table)
            (None, "PostHog/posthog", "mixgithub_posthog_posthog_pull_requests"),
            ("posthog/posthog.com", "posthog/posthog.com", "mixgithub_posthog_posthog_com_pull_requests"),
            ("POSTHOG/POSTHOG", "PostHog/posthog", "mixgithub_posthog_posthog_pull_requests"),
        ]
    )
    def test_multi_repo_source_scopes_by_repo(self, repo: str | None, expected_repo: str, expected_pr: str) -> None:
        # One source, two repos: the legacy repo keeps bare names, the added repo is qualified. A
        # `repo`-scoped read must reach the added repo's own tables, never mix them with the legacy
        # repo's; the default (no repo) resolves the legacy repo first, as a single-repo source did.
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
        # `synced` drives the default page's label: a repo is synced only with both pull_requests and
        # workflow_runs, so a still-backfilling repo (only pull_requests) is flagged unsynced and the
        # default selection skips it — matching what the resolver reads.
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
        # A new source with no legacy repo: the default (unscoped) resolve must pick the first
        # *configured* repo, matching what the picker labels as githubSources[0] — an alphabetical
        # pick would query one repo while the UI names another.
        self._multi_repo_source(
            prefix="ordered",
            repos={
                "z/org": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "a/org": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        # _multi_repo_source stores repositories in dict order (z/org, a/org), so z/org is configured first.
        assert resolve_github_tables(team=self.team).repository == "z/org"

    def test_default_follows_configured_order_even_over_the_legacy_repo(self) -> None:
        # A legacy source (bare `repository`) whose `repositories` multi-select puts another repo first:
        # the default must resolve that configured-first repo, matching the picker's first entry — the
        # legacy repo gets no priority, or the UI would label repo A while the backend queried the legacy.
        self._multi_repo_source(
            prefix="legacyorder",
            legacy_repository="PostHog/posthog",
            repos={
                # posthog.com configured first (qualified); the legacy posthog repo second (bare names).
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        assert resolve_github_tables(team=self.team).repository == "posthog/posthog.com"

    def test_explicit_repo_does_not_fall_through_to_a_sibling_repo(self) -> None:
        # The picker lists a repo before it finishes syncing. Selecting one whose pull_requests/
        # workflow_runs pair is incomplete must surface not-connected — never silently resolve the
        # source's other (complete) repo, which would mix two repos' metrics.
        self._multi_repo_source(
            prefix="partial",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(PULL_REQUESTS_SCHEMA, True), (WORKFLOW_RUNS_SCHEMA, True)],
                # workflow_runs still backfilling — no complete pair for this repo yet.
                "posthog/posthog.com": [(PULL_REQUESTS_SCHEMA, True)],
            },
        )
        with self.assertRaises(GitHubSourceNotConnectedError):
            resolve_github_tables(team=self.team, repo="posthog/posthog.com")
        # The complete sibling still resolves on its own.
        assert resolve_github_tables(team=self.team, repo="PostHog/posthog").repository == "PostHog/posthog"

    def test_incomplete_exact_match_does_not_fall_through_to_a_bare_source(self) -> None:
        # An explicit repo whose own candidate exists but is half-synced must surface not-connected —
        # never fall through to another source's bare/unattributed rows, which belong to an unknown
        # repo. The bare fallback is only for when the requested repo has no candidate at all.
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
        # Without an exact match the bare rows still serve as the fallback (branch-hint reads).
        assert resolve_github_tables(team=self.team, repo="some/other").pull_requests == "baregithub_pull_requests"

    def test_cost_pairs_include_every_repo_in_a_source(self) -> None:
        # The cost view unions (jobs, runs) across repos. A multi-repo source must contribute one
        # pair per fully-synced repo — collapsing it to one repo silently under-counts the view.
        self._multi_repo_source(
            prefix="cost",
            legacy_repository="PostHog/posthog",
            repos={
                "PostHog/posthog": [(WORKFLOW_RUNS_SCHEMA, True), (WORKFLOW_JOBS_SCHEMA, True)],
                "posthog/posthog.com": [(WORKFLOW_RUNS_SCHEMA, True), (WORKFLOW_JOBS_SCHEMA, True)],
                # runs but no jobs — excluded, the view needs both.
                "posthog/other": [(WORKFLOW_RUNS_SCHEMA, True)],
            },
        )
        pairs = resolve_job_cost_source_pairs(self.team)
        assert set(pairs) == {
            ("costgithub_posthog_posthog_workflow_jobs", "costgithub_posthog_posthog_workflow_runs"),
            ("costgithub_posthog_posthog_com_workflow_jobs", "costgithub_posthog_posthog_com_workflow_runs"),
        }

    def test_picker_lists_one_entry_per_configured_repo(self) -> None:
        # A multi-repo source's `repositories` list drives the picker: one selectable (id, repo) per
        # configured repo, in order, so a repo picker offers every repo the source syncs — not just
        # the legacy one, and not the whole GitHub App's repo catalog.
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
    """A team with one GitHub source per repository: a repo-scoped read must resolve the source
    connected for that repo, not the oldest one. Skips when object storage is unreachable."""

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
        # Both sources are fully synced, so oldest-first would search repo A and miss the PR that only
        # exists in the newer repo B. The repo hint routes resolution to B.
        older = self._connect_source(source_id="src-a", prefix="repoa", repository="PostHog/posthog")
        newer = self._connect_source(source_id="src-b", prefix="repob", repository="PostHog/posthog.com")
        # Source A (older, other repo): synced but holds no PR on the branch.
        self._create_table("github_pull_requests", PULL_REQUESTS_COLUMNS, [], source=older, prefix="repoa")
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [], source=older, prefix="repoa")
        # Source B (newer, target repo): holds the feat/login PR.
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

        # Clone-URL casing: both the source hint and the repo filter compare case-insensitively.
        matches = api.resolve_branch(team=self.team, branch="feat/login", repo="posthog/POSTHOG.com")
        assert [(m.repo, m.number) for m in matches] == [("PostHog/posthog.com", 61)]
        # Without the repo hint the oldest source (A) is searched and the PR is missed.
        assert api.resolve_branch(team=self.team, branch="feat/login") == []
