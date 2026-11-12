"""Resolve a team's GitHub warehouse tables at query time.

A warehouse table's name is ``ExternalDataSource.prefix + <synced endpoint table>``, and the prefix
is free text the user sets, so no fixed ``github_*`` table name can be assumed. A source syncs one
repository (bare endpoint schema names) or several (``owner/repo.endpoint`` schema names), and both
shapes are grouped by repository here.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    CIDataFreshness,
    GitHubSource,
    GitHubSourceNotConnectedError,
)
from products.engineering_analytics.backend.logic.views import depot_ci, trunk_quarantined_tests, workflow_jobs
from products.engineering_analytics.backend.logic.views.source_schema import OPTIONAL_WORKFLOW_RUNS_COLUMNS
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.source_inputs import SourceInputsStore, UnreadableSourceInputsError
from products.warehouse_sources.backend.facade.sources import github_schema_repo_endpoint
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

PULL_REQUESTS_SCHEMA = "pull_requests"
WORKFLOW_RUNS_SCHEMA = "workflow_runs"
# Every endpoint below is optional at the source. A read must return no data, not fail, when one is unsynced.
WORKFLOW_JOBS_SCHEMA = "workflow_jobs"
TEAM_MEMBERS_SCHEMA = "team_members"
ISSUE_EVENTS_SCHEMA = "issue_events"
# A deployment without statuses never succeeded or failed, so consumers need both tables.
DEPLOYMENTS_SCHEMA = "deployments"
DEPLOYMENT_STATUSES_SCHEMA = "deployment_statuses"
REVIEWS_SCHEMA = "reviews"

# Synced by a Depot source, not the GitHub one.
DEPOT_JOB_ATTEMPTS_SCHEMA = "job_attempts"

# GitHub adds this column to an issue event only for a team review request, so it lands only once some
# pull request in the repo requested a team, and a read of it fails before that.
REQUESTED_TEAM_COLUMN = "requested_team"

# The role is not in the endpoint's documented user object, so a snapshot can land without this column.
MEMBER_ROLE_COLUMN = "role"

_CURATED_ENDPOINTS = frozenset(
    {
        PULL_REQUESTS_SCHEMA,
        WORKFLOW_RUNS_SCHEMA,
        WORKFLOW_JOBS_SCHEMA,
        TEAM_MEMBERS_SCHEMA,
        ISSUE_EVENTS_SCHEMA,
        DEPLOYMENTS_SCHEMA,
        DEPLOYMENT_STATUSES_SCHEMA,
        REVIEWS_SCHEMA,
    }
)

# Resolved names are interpolated into HogQL ``FROM`` clauses, so a name that is not a plain identifier is rejected.
_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class GitHubTables:
    """One repository's warehouse tables and the source they came from. A None table is not synced."""

    pull_requests: str
    workflow_runs: str
    workflow_jobs: str | None = None
    team_members: str | None = None
    issue_events: str | None = None
    deployments: str | None = None
    deployment_statuses: str | None = None
    reviews: str | None = None
    # True when the issue-events table has the REQUESTED_TEAM_COLUMN.
    issue_events_team_requests: bool = False
    # The OPTIONAL_WORKFLOW_RUNS_COLUMNS that the runs table has. A read selects NULL for the others.
    workflow_runs_optional_columns: frozenset[str] = frozenset()
    workflow_runs_synced_at: datetime | None = None
    workflow_jobs_synced_at: datetime | None = None
    repository: str = ""
    # Already filtered by the caller's per-source warehouse RBAC. A read outside the warehouse that needs
    # the repository's credential must take it from this source alone.
    source_id: str = ""


def resolve_github_tables(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> GitHubTables:
    """The tables of the first usable repository, which has both pull_requests and workflow_runs synced.

    Without ``source_id``, repositories that ``list_github_sources`` reports as synced are tried first,
    oldest source first. ``repo`` ('owner/name', case-insensitive) restricts the choice to that
    repository, also inside a chosen ``source_id``. ``user_access_control`` applies the user's
    per-source warehouse RBAC, and this is the only place the read path can apply it, because the
    curated HogQL runs with no user. ``None`` skips that filter.

    Raises ``GitHubSourceNotConnectedError`` when no usable repository matches, or ``ValueError`` when
    ``source_id`` is not a UUID.
    """
    queryset = _github_sources(team, user_access_control)
    if source_id is not None:
        queryset = queryset.filter(id=_as_source_uuid(source_id))
    candidates: Iterable[_RepoCandidate] = _repo_candidates(team=team, sources=queryset)
    if source_id is None:
        # An old source can still hold tables for a repo it no longer lists, and taking it by age
        # alone reads stale data instead of the live source.
        candidates = _listed_first(candidates)
    if repo:
        # An explicit repo must never resolve to a different named repo, because that mixes the metrics
        # of two repositories. Rows with no repository (a legacy single-repo source) stand in only when
        # no candidate matches exactly, so a half-synced exact match raises not-connected.
        wanted = repo.casefold()
        materialized = list(candidates)
        exact = [c for c in materialized if c.repository.casefold() == wanted]
        candidates = exact if exact else [c for c in materialized if c.repository == ""]
    for candidate in candidates:
        tables = candidate.tables.names
        pull_requests = tables.get(PULL_REQUESTS_SCHEMA)
        workflow_runs = tables.get(WORKFLOW_RUNS_SCHEMA)
        # Every read joins workflow_runs for CI status, so a repo with only pull_requests synced
        # cannot serve a complete result.
        if pull_requests and workflow_runs:
            return GitHubTables(
                pull_requests=pull_requests,
                workflow_runs=workflow_runs,
                workflow_jobs=tables.get(WORKFLOW_JOBS_SCHEMA),
                team_members=tables.get(TEAM_MEMBERS_SCHEMA),
                issue_events=tables.get(ISSUE_EVENTS_SCHEMA),
                deployments=tables.get(DEPLOYMENTS_SCHEMA),
                deployment_statuses=tables.get(DEPLOYMENT_STATUSES_SCHEMA),
                reviews=tables.get(REVIEWS_SCHEMA),
                issue_events_team_requests=candidate.tables.issue_events_team_requests,
                workflow_runs_optional_columns=candidate.tables.workflow_runs_optional_columns,
                workflow_runs_synced_at=candidate.tables.synced_at.get(WORKFLOW_RUNS_SCHEMA),
                workflow_jobs_synced_at=candidate.tables.synced_at.get(WORKFLOW_JOBS_SCHEMA),
                repository=candidate.repository,
                source_id=candidate.source_id,
            )
    if source_id is not None:
        raise GitHubSourceNotConnectedError(_NO_SELECTED_SOURCE)
    raise GitHubSourceNotConnectedError()


@dataclass(frozen=True)
class JobSourceTables:
    """One repository's job-level tables. Read runs and jobs through ``runs_source`` and ``jobs_source``,
    which add the repository's Depot CI, because the ``github_`` tables hold GitHub Actions alone."""

    github_workflow_jobs: str
    github_workflow_runs: str
    pull_requests: str | None = None
    issue_events: str | None = None
    reviews: str | None = None
    source_id: str = ""
    repository: str = ""
    depot_job_attempts: depot_ci.DepotJobAttempts | None = None
    workflow_runs_optional_columns: frozenset[str] = frozenset()

    @property
    def runs_source(self) -> str:
        return depot_ci.with_depot_runs(
            self.github_workflow_runs,
            self.depot_job_attempts,
            self.pull_requests,
            self.github_workflow_jobs,
            optional_columns=self.workflow_runs_optional_columns,
        )

    @property
    def jobs_source(self) -> workflow_jobs.JobsTable:
        return depot_ci.with_depot_jobs(self.github_workflow_jobs, self.depot_job_attempts, self.github_workflow_runs)


def resolve_job_source_tables(team: Team) -> list[JobSourceTables]:
    """One entry per repository that has both workflow_jobs and workflow_runs synced, across every source.

    Applies no per-user access control, because the view sync that calls it runs with no user.
    """
    entries: list[tuple[str, JobSourceTables]] = []
    for source in _github_sources(team):
        for repository, repo_tables in _synced_tables_by_repo(team=team, source=source).items():
            tables = repo_tables.names
            runs = tables.get(WORKFLOW_RUNS_SCHEMA)
            jobs = tables.get(WORKFLOW_JOBS_SCHEMA)
            if runs and jobs:
                entry = JobSourceTables(
                    github_workflow_jobs=jobs,
                    github_workflow_runs=runs,
                    pull_requests=tables.get(PULL_REQUESTS_SCHEMA),
                    issue_events=tables.get(ISSUE_EVENTS_SCHEMA),
                    reviews=tables.get(REVIEWS_SCHEMA),
                    source_id=str(source.id),
                    repository=repository,
                    workflow_runs_optional_columns=repo_tables.workflow_runs_optional_columns,
                )
                entries.append((repository, entry))
    # The views union every entry, so a repository that two GitHub sources sync takes its Depot table on
    # one entry only, or every Depot job and its cost would count twice. Entries with the PR snapshot go
    # first, because the friction view reads only those entries.
    entries.sort(key=lambda repository_entry: repository_entry[1].pull_requests is None)
    depot_tables = resolve_depot_job_attempts_tables(team)
    return [replace(entry, depot_job_attempts=depot_tables.pop(repository, None)) for repository, entry in entries]


@dataclass(frozen=True)
class TeamMembershipTable:
    table: str
    has_role: bool


def resolve_team_membership_table(
    *, team: Team, user_access_control: "UserAccessControl | None" = None
) -> TeamMembershipTable | None:
    """The team's synced ``team_members`` table, or None when no source syncs it.

    Does not require ``pull_requests`` or ``workflow_runs``, so a source that syncs the roster alone
    still resolves. Membership is org-scoped, so the first match wins.
    """
    for source in _github_sources(team, user_access_control):
        legacy_repo = _source_repository(source) or None
        for schema in _synced_schemas(team=team, source=source):
            _, endpoint = github_schema_repo_endpoint(schema.schema_metadata, schema.name, legacy_repo)
            if endpoint != TEAM_MEMBERS_SCHEMA:
                continue
            table = schema.table
            if table is None or table.deleted or not _IDENTIFIER.match(table.name):
                continue
            return TeamMembershipTable(table=table.name, has_role=MEMBER_ROLE_COLUMN in (table.columns or {}))
    return None


TRUNK_MERGE_QUEUE_SCHEMA = "MergeQueuePullRequests"


def resolve_trunk_merge_queue_table(team: Team, user_access_control: "UserAccessControl | None" = None) -> str | None:
    """The first synced Trunk merge-queue table the caller may access, oldest source first, or None.

    Not scoped by repository. Callers must handle None, because the Trunk source does not select
    this endpoint by default.
    """
    for source in _accessible_sources(team, ExternalDataSourceType.TRUNKIO, user_access_control):
        table = _synced_table_name(team, source, TRUNK_MERGE_QUEUE_SCHEMA)
        if table:
            return table
    return None


TRUNK_QUARANTINED_TESTS_SCHEMA = "QuarantinedTests"


@frozen
class TrunkQuarantineSource:
    table: str
    org_url_slug: str | None
    # False until a source moved to the v2 API resyncs, so the board keeps reading the v1 columns.
    v2_shape: bool


def resolve_trunk_quarantined_tests_source(
    team: Team, repository: str, user_access_control: "UserAccessControl | None" = None
) -> TrunkQuarantineSource | None:
    """The quarantined-tests table of the Trunk source configured for ``repository``, or None.

    Falls back to the oldest synced source that names no repository.
    """
    fallback: TrunkQuarantineSource | None = None
    for source in _accessible_sources(team, ExternalDataSourceType.TRUNKIO, user_access_control):
        for schema in _synced_schemas(team=team, source=source):
            if schema.name != TRUNK_QUARANTINED_TESTS_SCHEMA:
                continue
            table = schema.table
            if table is None or table.deleted or not _IDENTIFIER.match(table.name):
                continue
            try:
                inputs = SourceInputsStore.load(source)
            except UnreadableSourceInputsError:
                inputs = {}
            resolved = TrunkQuarantineSource(
                table=table.name,
                org_url_slug=inputs.get("org_url_slug") or None,
                v2_shape=trunk_quarantined_tests.V2_SHAPE_COLUMN in (table.columns or {}),
            )
            owner, name = inputs.get("repo_owner") or "", inputs.get("repo_name") or ""
            if f"{owner}/{name}".lower() == repository.lower():
                return resolved
            # A source that names another repository holds that repository's quarantines.
            if not owner and not name:
                fallback = fallback or resolved
    return fallback


def build_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    return list_github_sources(team=team, user_access_control=user_access_control)


def list_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    """One entry per repository each accessible source is configured to sync, oldest source first.

    A configured repository is listed before it finishes syncing, and ``synced`` says whether it has
    both endpoints ``resolve_github_tables`` needs. A source with no configured repository yields one
    entry with a blank ``repo``. Pass an entry's ``id`` and ``repo`` back as ``source_id`` and ``repo``.
    """
    entries: list[GitHubSource] = []
    for source in _github_sources(team, user_access_control):
        by_repo = _synced_tables_by_repo(team=team, source=source)
        synced_repos = {
            repo
            for repo, tables in by_repo.items()
            if PULL_REQUESTS_SCHEMA in tables.names and WORKFLOW_RUNS_SCHEMA in tables.names
        }
        for repo in _configured_repositories(source) or [""]:
            entries.append(
                GitHubSource(
                    id=str(source.id),
                    repo=repo,
                    prefix=source.prefix or "",
                    synced=repo.casefold() in synced_repos,
                )
            )
    return entries


class _RepoTables(NamedTuple):
    # Keyed by endpoint.
    names: dict[str, str]
    issue_events_team_requests: bool
    workflow_runs_optional_columns: frozenset[str]
    # Keyed by endpoint, for the same schemas as ``names``.
    synced_at: dict[str, datetime | None]


class _RepoCandidate(NamedTuple):
    # The source's ``repository`` input in its original case for the legacy repo, the casefolded
    # ``owner/repo`` for any other repo, or '' when a bare schema row has no repository.
    repository: str
    tables: _RepoTables
    source_id: str
    # True when the source lists this repo, so ``list_github_sources`` reports it as synced.
    listed: bool


def _listed_first(candidates: Iterable[_RepoCandidate]) -> Iterator[_RepoCandidate]:
    """Listed candidates in order, then the unlisted ones. Lazy, so later sources are not queried early."""
    unlisted: list[_RepoCandidate] = []
    for candidate in candidates:
        if candidate.listed:
            yield candidate
        else:
            unlisted.append(candidate)
    yield from unlisted


def _repo_candidates(*, team: Team, sources: QuerySet[ExternalDataSource]) -> Iterator[_RepoCandidate]:
    """Every repository the sources expose, in default-resolution order.

    Sources keep their order. Within a source, repositories follow the configured order, then the
    unconfigured ones sorted by name. Lazy, with one schema query per source.
    """
    for source in sources:
        display = _source_repository(source)
        legacy_key = display.casefold()
        # The configured order is the order ``list_github_sources`` lists, so the default repository
        # here is the first entry of that list.
        configured = [repo.casefold() for repo in _configured_repositories(source)]

        def order_key(repo_key: str, *, configured: list[str] = configured) -> tuple:
            position = configured.index(repo_key) if repo_key in configured else len(configured)
            return (position, repo_key)

        by_repo = _synced_tables_by_repo(team=team, source=source)
        for repo_key in sorted(by_repo, key=order_key):
            repository = display if repo_key == legacy_key else repo_key
            # ``list_github_sources`` lists one blank entry for a source with no configured repository.
            listed = repo_key in configured if configured else repo_key == ""
            yield _RepoCandidate(
                repository=repository, tables=by_repo[repo_key], source_id=str(source.id), listed=listed
            )


def _github_sources(team: Team, user_access_control: "UserAccessControl | None" = None) -> QuerySet[ExternalDataSource]:
    return _accessible_sources(team, ExternalDataSourceType.GITHUB, user_access_control)


def _accessible_sources(
    team: Team, source_type: ExternalDataSourceType, user_access_control: "UserAccessControl | None"
) -> QuerySet[ExternalDataSource]:
    """The team's non-deleted sources of ``source_type``, oldest first.

    ``user_access_control`` applies the user's per-source warehouse RBAC. ``None`` skips it, for
    callers that run with no user.
    """
    sources = (
        ExternalDataSource.objects.filter(team_id=team.pk, source_type=source_type)
        .exclude(deleted=True)
        .order_by("created_at", "id")
    )
    if user_access_control is not None:
        sources = user_access_control.filter_queryset_by_access_level(sources)
    return sources


_NO_SELECTED_SOURCE = "The selected GitHub source isn't connected or has no synced pull_requests/workflow_runs tables."


def _source_repository(source: ExternalDataSource) -> str:
    """The source's ``repository`` input, or '' when it is unset or the inputs are unreadable."""
    try:
        job_inputs = SourceInputsStore.load(source)
    except UnreadableSourceInputsError:
        return ""
    return str(job_inputs.get("repository") or "").strip()


def _configured_repositories(source: ExternalDataSource) -> list[str]:
    """The ``owner/repo`` names a source is configured to sync, in order and original case.

    Duplicates are dropped case-insensitively. Never raises.
    """
    try:
        job_inputs = SourceInputsStore.load(source)
    except UnreadableSourceInputsError:
        return []
    repositories = job_inputs.get("repositories")
    # The sync treats an empty ``repositories`` list as unset and syncs the single ``repository``.
    raw = repositories if isinstance(repositories, list) and repositories else [job_inputs.get("repository")]
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        name = str(value or "").strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _as_source_uuid(source_id: str) -> UUID:
    try:
        return UUID(source_id)
    except ValueError as err:
        raise ValueError(f"source_id must be a UUID, got: {source_id!r}") from err


def resolve_depot_job_attempts_tables(
    team: Team, user_access_control: "UserAccessControl | None" = None
) -> dict[str, depot_ci.DepotJobAttempts]:
    """The team's synced Depot CI job attempts, keyed by the casefolded ``owner/repo`` of each source's
    ``repository`` input. The oldest source wins for a repository."""
    return {
        repository: depot.attempts
        for repository, depot in _depot_job_attempts_by_repo(team, user_access_control).items()
    }


@frozen
class _SyncedDepotJobAttempts:
    attempts: depot_ci.DepotJobAttempts
    synced_at: datetime | None


def _depot_job_attempts_by_repo(
    team: Team, user_access_control: "UserAccessControl | None"
) -> dict[str, _SyncedDepotJobAttempts]:
    by_repo: dict[str, _SyncedDepotJobAttempts] = {}
    for source in _accessible_sources(team, ExternalDataSourceType.DEPOT, user_access_control):
        repository = _source_repository(source).casefold()
        schema = _synced_schema(team, source, DEPOT_JOB_ATTEMPTS_SCHEMA) if repository else None
        table = schema.table if schema is not None else None
        attempts = depot_ci.DepotJobAttempts.for_repository(table.name, repository) if table is not None else None
        if schema is not None and attempts is not None:
            by_repo.setdefault(repository, _SyncedDepotJobAttempts(attempts=attempts, synced_at=schema.last_synced_at))
    return by_repo


def resolve_ci_data_freshness(
    *, team: Team, tables: GitHubTables, user_access_control: "UserAccessControl | None" = None
) -> CIDataFreshness:
    """When the CI data that ``tables`` reads was last synced.

    With Depot CI synced for the repository, each time is the older of the GitHub and Depot syncs,
    and None when either never synced.
    """
    depot = _depot_job_attempts_by_repo(team, user_access_control).get(tables.repository.casefold())

    def watermark(github_synced_at: datetime | None) -> datetime | None:
        if depot is None:
            return github_synced_at
        if github_synced_at is None or depot.synced_at is None:
            return None
        return min(github_synced_at, depot.synced_at)

    return CIDataFreshness(
        runs_synced_at=watermark(tables.workflow_runs_synced_at),
        jobs_synced_at=watermark(tables.workflow_jobs_synced_at) if tables.workflow_jobs else None,
    )


def depot_source_api_token(team: Team, source_id: str) -> str | None:
    """The API token a team's Depot source syncs with, or None. Applies no per-user access control."""
    source = _accessible_sources(team, ExternalDataSourceType.DEPOT, None).filter(id=source_id).first()
    try:
        inputs = SourceInputsStore.load(source) if source is not None else {}
    except UnreadableSourceInputsError:
        inputs = {}
    api_token = inputs.get("api_token")
    return api_token if isinstance(api_token, str) and api_token else None


def depot_source_job_attempts_table(team: Team, source: ExternalDataSource) -> str | None:
    return _synced_table_name(team, source, DEPOT_JOB_ATTEMPTS_SCHEMA)


def depot_source_job_attempts(team: Team, source: ExternalDataSource) -> depot_ci.DepotJobAttempts | None:
    """One Depot source's job attempts, scoped to its ``repository`` input, or None."""
    table = depot_source_job_attempts_table(team, source)
    repository = _source_repository(source).casefold()
    return depot_ci.DepotJobAttempts.for_repository(table, repository) if table and repository else None


def _synced_table_name(team: Team, source: ExternalDataSource, schema_name: str) -> str | None:
    schema = _synced_schema(team, source, schema_name)
    return schema.table.name if schema is not None and schema.table is not None else None


def _synced_schema(team: Team, source: ExternalDataSource, schema_name: str) -> ExternalDataSchema | None:
    for schema in _synced_schemas(team=team, source=source):
        table = schema.table
        if schema.name == schema_name and table is not None and not table.deleted and _IDENTIFIER.match(table.name):
            return schema
    return None


def _synced_schemas(*, team: Team, source: ExternalDataSource) -> QuerySet[ExternalDataSchema]:
    return (
        ExternalDataSchema.objects.filter(team_id=team.pk, source_id=source.id, should_sync=True)
        .exclude(deleted=True)
        .select_related("table")
    )


def _synced_tables_by_repo(*, team: Team, source: ExternalDataSource) -> dict[str, _RepoTables]:
    """A source's synced curated tables, keyed by repository.

    The key is the repository ``github_schema_repo_endpoint`` resolves for each schema row, or '' when
    a bare row has no repository.
    """
    legacy_repo = _source_repository(source) or None
    by_repo: dict[str, dict[str, str]] = {}
    team_requests_by_repo: dict[str, bool] = {}
    run_columns_by_repo: dict[str, frozenset[str]] = {}
    synced_at_by_repo: dict[str, dict[str, datetime | None]] = {}
    for schema in _synced_schemas(team=team, source=source):
        repository, endpoint = github_schema_repo_endpoint(schema.schema_metadata, schema.name, legacy_repo)
        if endpoint not in _CURATED_ENDPOINTS:
            continue
        table = schema.table
        if table is not None and not table.deleted and _IDENTIFIER.match(table.name):
            by_repo.setdefault(repository or "", {})[endpoint] = table.name
            synced_at_by_repo.setdefault(repository or "", {})[endpoint] = schema.last_synced_at
            if endpoint == ISSUE_EVENTS_SCHEMA:
                team_requests_by_repo[repository or ""] = REQUESTED_TEAM_COLUMN in (table.columns or {})
            if endpoint == WORKFLOW_RUNS_SCHEMA:
                run_columns_by_repo[repository or ""] = frozenset(OPTIONAL_WORKFLOW_RUNS_COLUMNS) & frozenset(
                    table.columns or {}
                )
    return {
        repository: _RepoTables(
            names=names,
            issue_events_team_requests=team_requests_by_repo.get(repository, False),
            workflow_runs_optional_columns=run_columns_by_repo.get(repository, frozenset()),
            synced_at=synced_at_by_repo.get(repository, {}),
        )
        for repository, names in by_repo.items()
    }
