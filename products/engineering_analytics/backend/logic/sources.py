"""Resolve a team's GitHub warehouse tables at query time.

A warehouse table's real name is ``ExternalDataSource.prefix + <synced endpoint table>``,
and ``prefix`` is free text the user sets when connecting the source. The product can
therefore never assume a fixed ``github_*`` table name — a team that connected GitHub
with prefix ``devex_eng_analytics`` lands its data in ``devex_eng_analyticsgithub_pull_requests``.

This resolver walks the team's connected GitHub source(s) to their ``pull_requests`` /
``workflow_runs`` schemas and returns the actual ``DataWarehouseTable`` names the curated
builders should read. Names are resolved exactly once per request (in the logic layer)
and threaded down into the builders, so a request hits the warehouse models a single time.

A team can connect GitHub more than once (e.g. one source per repository). A caller may pass
``source_id`` to read a specific source; otherwise the oldest connected source with both
endpoints synced is used.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import QuerySet

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import GitHubSource, GitHubSourceNotConnectedError
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
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

# Resolved names are interpolated into HogQL ``FROM`` clauses. Warehouse table names are
# always plain identifiers (the prefix is validated to ``[A-Za-z0-9_]`` at connect time and
# the rest is the fixed ``github_<endpoint>`` suffix), so reject anything else defensively
# rather than trust an unexpected name into SQL.
_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class GitHubTables:
    """The per-team warehouse table names the curated builders read from."""

    pull_requests: str
    workflow_runs: str
    # Optional: present only once the job-level source is synced; None means "no jobs data".
    workflow_jobs: str | None = None


def resolve_github_tables(
    *, team: Team, source_id: str | None = None, user_access_control: "UserAccessControl | None" = None
) -> GitHubTables:
    """Resolve the team's curated GitHub table names from its warehouse models.

    With ``source_id``, reads that specific connected GitHub source; otherwise picks the
    oldest source with both endpoints synced (oldest = the team's first/established connection)
    — deterministic when a team has more than one GitHub source (e.g. one per repository).
    Raises ``GitHubSourceNotConnectedError`` when no matching usable source exists (the
    presentation layer maps it to a 400, so the UI prompts to connect a source and an agent gets
    an actionable error), or ``ValueError`` when ``source_id`` is not a UUID.

    ``user_access_control`` enforces the requesting user's per-source warehouse RBAC (applied in
    ``_github_sources``): a denied ``source_id`` raises (400) and the default-oldest path skips it.
    The curated HogQL runs team-scoped with no user and HogQL does not enforce per-user ACL on
    warehouse tables, so honoring it here is the only way the read path can. ``None`` (system/
    Temporal/CLI contexts with no request user) skips filtering — team scoping still holds.
    """
    sources = _github_sources(team, user_access_control)
    if source_id is not None:
        sources = sources.filter(id=_as_source_uuid(source_id))
    for source in sources:
        tables = _synced_table_names(team=team, source=source)
        pull_requests = tables.get(PULL_REQUESTS_SCHEMA)
        workflow_runs = tables.get(WORKFLOW_RUNS_SCHEMA)
        # Both endpoints are required together, by design: every read surface (cards, PR list,
        # lifecycle) joins workflow_runs for CI status and the push / re-run rollup, so a source
        # with only pull_requests synced can't serve a complete result. The trade-off is that a
        # half-synced source makes the whole product 400 (e.g. while workflow_runs is still
        # backfilling) instead of degrading to PRs-without-CI. Relaxing this to a graceful
        # PR-only mode (null CI columns) is a deliberate future change, not handled here.
        if pull_requests and workflow_runs:
            # workflow_jobs is optional — included when synced, None otherwise (jobs degrade to empty).
            return GitHubTables(
                pull_requests=pull_requests,
                workflow_runs=workflow_runs,
                workflow_jobs=tables.get(WORKFLOW_JOBS_SCHEMA),
            )
    if source_id is not None:
        raise GitHubSourceNotConnectedError(_NO_SELECTED_SOURCE)
    raise GitHubSourceNotConnectedError()


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
            repo=str((source.job_inputs or {}).get("repository") or ""),
            prefix=source.prefix or "",
        )
        for source in _github_sources(team, user_access_control)
    ]


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
    return sources


# Distinct from the no-source message: the caller picked a source that isn't a usable GitHub
# source for this team (wrong id, another team's source, or its endpoints aren't synced).
_NO_SELECTED_SOURCE = "The selected GitHub source isn't connected or has no synced pull_requests/workflow_runs tables."


def _as_source_uuid(source_id: str) -> UUID:
    try:
        return UUID(source_id)
    except ValueError as err:
        raise ValueError(f"source_id must be a UUID, got: {source_id!r}") from err


def _synced_table_names(*, team: Team, source: ExternalDataSource) -> dict[str, str]:
    """Map ``{endpoint: table name}`` for a source's actively-synced PR/CI schemas."""
    schemas = (
        ExternalDataSchema.objects.filter(
            team_id=team.pk,
            source_id=source.id,
            should_sync=True,
            name__in=(PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA),
        )
        .exclude(deleted=True)
        .select_related("table")
    )
    resolved: dict[str, str] = {}
    for schema in schemas:
        table = schema.table
        if table is not None and not table.deleted and _IDENTIFIER.match(table.name):
            resolved[schema.name] = table.name
    return resolved
