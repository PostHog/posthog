"""Resolve a team's GitHub warehouse tables at query time.

A warehouse table's real name is ``ExternalDataSource.prefix + <synced endpoint table>``,
and ``prefix`` is free text the user sets when connecting the source. The product can
therefore never assume a fixed ``github_*`` table name — a team that connected GitHub
with prefix ``devex_eng_analytics`` lands its data in ``devex_eng_analyticsgithub_pull_requests``.

This resolver walks the team's connected GitHub source(s) to their ``pull_requests`` /
``workflow_runs`` schemas and returns the actual ``DataWarehouseTable`` names the curated
builders should read. Names are resolved exactly once per request (in the logic layer)
and threaded down into the builders, so a request hits the warehouse models a single time.

A team reaches a repo in one of two ways, handled uniformly here: one source per repository
(each with its own bare endpoint names), or one source syncing several repositories (the
multi-repo GitHub source, whose added repos carry repo-qualified ``owner/repo.endpoint`` schema
names while its original repo keeps bare names). Every schema row is grouped under its repo via
the warehouse_sources facade, so both shapes resolve the same way. A caller may pass ``source_id``
to read a specific source; otherwise the oldest source's repos are tried first, or — when a
``repo`` ('owner/name') is passed — the matching repo across all sources is preferred.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.models.team import Team
from posthog.rbac.user_access_control import NO_ACCESS_LEVEL

from products.engineering_analytics.backend.facade.contracts import GitHubSource, GitHubSourceNotConnectedError
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.sources import github_schema_repo_endpoint
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl

# GitHub source endpoints (``ExternalDataSchema.name``) backing the curated builders. The
# materialized table for each is ``prefix + "github_" + endpoint``, e.g. with prefix
# ``devex_eng_analytics`` the pull-requests table is ``devex_eng_analyticsgithub_pull_requests``.
PULL_REQUESTS_SCHEMA = "pull_requests"
WORKFLOW_RUNS_SCHEMA = "workflow_runs"
# Job-level CI (queue time, per-job duration, runner tier). Optional — the source/sync lands
# separately, so reads must degrade gracefully (no jobs) rather than require it like the pair above.
WORKFLOW_JOBS_SCHEMA = "workflow_jobs"
# GitHub org team membership (login → team slug), the author→team key behind team-level merge
# timing. Optional and off by default at the source (needs the org Members:Read grant), so reads
# must degrade gracefully (no membership data) exactly like workflow_jobs.
TEAM_MEMBERS_SCHEMA = "team_members"

# The curated endpoints we resolve per repo. A source's other synced endpoints (issues, commits,
# teams, …) are irrelevant to the CI/PR read layer and dropped during grouping.
_CURATED_ENDPOINTS = frozenset({PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA, TEAM_MEMBERS_SCHEMA})

# Resolved names are interpolated into HogQL ``FROM`` clauses. Warehouse table names are
# always plain identifiers (the prefix is validated to ``[A-Za-z0-9_]`` at connect time and
# the rest is the fixed ``github_<endpoint>`` suffix), so reject anything else defensively
# rather than trust an unexpected name into SQL.
_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class GitHubTables:
    """The selected GitHub source identity and warehouse tables the curated layer reads."""

    pull_requests: str
    workflow_runs: str
    # Optional: present only once the job-level source is synced; None means "no jobs data".
    workflow_jobs: str | None = None
    # Optional: present only once org team membership is synced; None means "no membership data".
    team_members: str | None = None
    # Used to scope cross-store reads such as CI traces to the selected source's repository.
    repository: str = ""


def resolve_github_tables(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> GitHubTables:
    """Resolve the team's curated GitHub table names from its warehouse models.

    With ``source_id``, reads that specific connected GitHub source; otherwise picks the oldest
    source's first usable repo with both endpoints synced (oldest = the team's first/established
    connection) — deterministic when a team has more than one source or a source syncs more than
    one repo. Raises ``GitHubSourceNotConnectedError`` when no matching usable repo exists (the
    presentation layer maps it to a 400, so the UI prompts to connect a source and an agent gets
    an actionable error), or ``ValueError`` when ``source_id`` is not a UUID.

    ``repo`` ('owner/name') scopes a repo-specific call — a team with several repos otherwise always
    resolves the oldest, so a repo-scoped read (e.g. ``resolve_branch``) would search the wrong
    repo's tables. When ``repo`` is given (and ``source_id`` is not), repos whose resolved identity
    equals it (case-insensitively) are tried first; the rest still follow as a fallback, since a
    bare row's repo can be empty while its data holds the repo.

    ``user_access_control`` enforces the requesting user's per-source warehouse RBAC (applied in
    ``_github_sources``): a denied ``source_id`` raises (400) and the default-oldest path skips it.
    The curated HogQL runs team-scoped with no user and HogQL does not enforce per-user ACL on
    warehouse tables, so honoring it here is the only way the read path can. ``None`` (system/
    Temporal/CLI contexts with no request user) skips filtering — team scoping still holds.
    """
    queryset = _github_sources(team, user_access_control)
    if source_id is not None:
        queryset = queryset.filter(id=_as_source_uuid(source_id))
    candidates = _repo_candidates(team=team, sources=queryset)
    if repo and source_id is None:
        # Stable sort keeps the source-oldest / legacy-repo-first order among equals; the matching
        # repo(s) just move to the front. The non-matching tail still follows as a fallback, since a
        # source's `repository` input can be empty while its data holds the repo.
        wanted = repo.casefold()
        candidates.sort(key=lambda candidate: candidate.repository.casefold() != wanted)
    for candidate in candidates:
        tables = candidate.tables
        pull_requests = tables.get(PULL_REQUESTS_SCHEMA)
        workflow_runs = tables.get(WORKFLOW_RUNS_SCHEMA)
        # Both endpoints are required together, by design: every read surface (cards, PR list,
        # lifecycle) joins workflow_runs for CI status and the push / re-run rollup, so a repo
        # with only pull_requests synced can't serve a complete result. The trade-off is that a
        # half-synced repo makes the whole product 400 (e.g. while workflow_runs is still
        # backfilling) instead of degrading to PRs-without-CI. Relaxing this to a graceful
        # PR-only mode (null CI columns) is a deliberate future change, not handled here.
        if pull_requests and workflow_runs:
            # workflow_jobs / team_members are optional: included when synced, None otherwise
            # (jobs degrade to empty, membership-keyed reads degrade to "no membership data").
            return GitHubTables(
                pull_requests=pull_requests,
                workflow_runs=workflow_runs,
                workflow_jobs=tables.get(WORKFLOW_JOBS_SCHEMA),
                team_members=tables.get(TEAM_MEMBERS_SCHEMA),
                repository=candidate.repository,
            )
    if source_id is not None:
        raise GitHubSourceNotConnectedError(_NO_SELECTED_SOURCE)
    raise GitHubSourceNotConnectedError()


def resolve_job_cost_source_pairs(team: Team) -> list[tuple[str, str]]:
    """``(jobs_table, runs_table)`` for every synced repo with BOTH the jobs and runs endpoints.

    Used to build the exposed per-job cost view, which unions across all of a team's qualifying
    repos. Unlike ``resolve_github_tables`` (which needs pull_requests + workflow_runs and returns
    one repo), this needs workflow_jobs + workflow_runs and returns all of them — the cost view has
    no PR dependency and shouldn't collapse a team's repos to one. A multi-repo source contributes
    one pair per repo, so the view stays complete when one source syncs several repos. Userless
    (the view sync runs in a system/Temporal context); team scoping is the boundary.
    """
    pairs: list[tuple[str, str]] = []
    for source in _github_sources(team):
        for tables in _synced_tables_by_repo(team=team, source=source).values():
            runs = tables.get(WORKFLOW_RUNS_SCHEMA)
            jobs = tables.get(WORKFLOW_JOBS_SCHEMA)
            if runs and jobs:
                pairs.append((jobs, runs))
    return pairs


def list_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    """The team's connected GitHub sources the caller may access, as selectable refs, oldest first.

    Lists every non-deleted GitHub source the user can access — including ones whose endpoints aren't
    fully synced yet — so a source picker shows everything they connected; selecting an unusable one
    surfaces the same connect prompt ``resolve_github_tables`` drives. Sources the user can't access
    (``user_access_control``) are filtered out, so the picker can't enumerate them. Each ``id`` is
    what the caller passes back as ``source_id`` to read that source.
    """
    return [
        GitHubSource(
            id=str(source.id),
            repo=_source_repository(source),
            prefix=source.prefix or "",
        )
        for source in _github_sources(team, user_access_control)
    ]


class _RepoCandidate(NamedTuple):
    # Display repo: the source's original-case ``repository`` for its legacy/bare repo (``''`` when
    # a bare row has no repo to attribute it to); the parsed ``owner/repo`` for a qualified repo.
    repository: str
    # ``{endpoint: table name}`` for this one repo's synced curated schemas.
    tables: dict[str, str]


def _repo_candidates(*, team: Team, sources: QuerySet[ExternalDataSource]) -> list[_RepoCandidate]:
    """Every ``(repo, tables)`` a team's GitHub sources expose, in default-resolution order.

    Sources keep their oldest-first order (the established connection wins), and within a source
    the legacy/bare repo comes first — so a single-repo source resolves exactly as before — then
    any added repos, sorted, for a deterministic pick. A multi-repo source contributes one entry
    per repo, so a repo-scoped read can reach a repo that isn't the source's legacy one.
    """
    candidates: list[_RepoCandidate] = []
    for source in sources:
        display = _source_repository(source)
        legacy_key = display.casefold()
        by_repo = _synced_tables_by_repo(team=team, source=source)
        for repo_key in sorted(by_repo, key=lambda key: (key != legacy_key, key)):
            repository = display if repo_key == legacy_key else repo_key
            candidates.append(_RepoCandidate(repository=repository, tables=by_repo[repo_key]))
    return candidates


def _github_sources(team: Team, user_access_control: "UserAccessControl | None" = None) -> QuerySet[ExternalDataSource]:
    """The team's non-deleted GitHub sources the caller may access, oldest first — the order
    ``resolve_github_tables`` defaults from, so a picker's first entry matches the default source.

    ``user_access_control`` applies the requesting user's per-source warehouse RBAC, so neither the
    resolver nor the picker can reach a source the user can't access; ``None`` (system/Temporal/CLI
    contexts) skips it, leaving team scoping. This is the single place that access scope is decided.
    """
    sources = (
        ExternalDataSource.objects.filter(team_id=team.pk, source_type=ExternalDataSourceType.GITHUB)
        .exclude(deleted=True)
        .order_by("created_at", "id")
    )
    if user_access_control is not None:
        sources = user_access_control.filter_queryset_by_access_level(sources)
        if not user_access_control.has_resource_access("external_data_source"):
            # "none" resource-level access: the platform filter drops nothing when the user holds no
            # object grants, so fail closed here to self-created or explicitly granted sources.
            granted_ids = [
                source.id
                for source in sources
                if (level := user_access_control.access_level_for_object(source, explicit=True))
                and level != NO_ACCESS_LEVEL
            ]
            sources = sources.filter(Q(created_by=user_access_control.user) | Q(id__in=granted_ids))
    return sources


# Distinct from the no-source message: the caller picked a source that isn't a usable GitHub
# source for this team (wrong id, another team's source, or its endpoints aren't synced).
_NO_SELECTED_SOURCE = "The selected GitHub source isn't connected or has no synced pull_requests/workflow_runs tables."


def _source_repository(source: ExternalDataSource) -> str:
    """The source's configured ``owner/repo`` identity, or '' when unset.

    ``job_inputs`` is an ``EncryptedJSONField`` that can hold any JSON value, so a non-dict
    (list/str) would crash the ``.get`` below — guard it the same way ``job_logs.coordinator``
    does, since this resolves for every engineering_analytics endpoint.
    """
    job_inputs = source.job_inputs
    if not isinstance(job_inputs, dict):
        return ""
    return str(job_inputs.get("repository") or "").strip()


def _as_source_uuid(source_id: str) -> UUID:
    try:
        return UUID(source_id)
    except ValueError as err:
        raise ValueError(f"source_id must be a UUID, got: {source_id!r}") from err


def _schema_metadata(schema: ExternalDataSchema) -> dict | None:
    """The row's persisted ``sync_type_config.schema_metadata`` (repo/endpoint location), or None.

    ``sync_type_config`` is a JSONField that also holds unrelated bookkeeping (xmin cursors), so
    guard for a non-dict config and a non-dict metadata value before handing it to the resolver.
    """
    config = schema.sync_type_config
    if not isinstance(config, dict):
        return None
    metadata = config.get("schema_metadata")
    return metadata if isinstance(metadata, dict) else None


def _synced_tables_by_repo(*, team: Team, source: ExternalDataSource) -> dict[str, dict[str, str]]:
    """Map ``{repository: {endpoint: table name}}`` for a source's actively-synced curated schemas.

    A source syncs one repo (legacy bare endpoint names like ``pull_requests``) or several
    (repo-qualified names like ``owner/repo.pull_requests``, the multi-repo GitHub source). Each
    row resolves to its ``(repository, endpoint)`` through the warehouse_sources facade — persisted
    metadata first, qualified-name parse second, the source's legacy ``repository`` for bare rows
    last. Repo keys are normalized (lowercased, since GitHub full names are case-insensitive); a
    bare row with no legacy repo groups under ``''`` — the pre-multi-repo single-repo shape.
    """
    legacy_repo = _source_repository(source) or None
    schemas = (
        ExternalDataSchema.objects.filter(team_id=team.pk, source_id=source.id, should_sync=True)
        .exclude(deleted=True)
        .select_related("table")
    )
    by_repo: dict[str, dict[str, str]] = {}
    for schema in schemas:
        repository, endpoint = github_schema_repo_endpoint(schema.name, _schema_metadata(schema), legacy_repo)
        if endpoint not in _CURATED_ENDPOINTS:
            continue
        table = schema.table
        if table is not None and not table.deleted and _IDENTIFIER.match(table.name):
            by_repo.setdefault(repository or "", {})[endpoint] = table.name
    return by_repo
