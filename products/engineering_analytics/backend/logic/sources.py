"""Resolve a team's GitHub warehouse tables at query time.

A warehouse table's real name is ``ExternalDataSource.prefix + <synced endpoint table>``,
and ``prefix`` is free text the user sets when connecting the source. The product can
therefore never assume a fixed ``github_*`` table name — a team that connected GitHub
with prefix ``devex_eng_analytics`` lands its data in ``devex_eng_analyticsgithub_pull_requests``.

This resolver walks the team's connected GitHub source(s) to their ``pull_requests`` /
``workflow_runs`` schemas and returns the actual ``DataWarehouseTable`` names the curated
builders should read. Names are resolved exactly once per request (in the logic layer)
and threaded down into the builders, so a request hits the warehouse models a single time.
"""

import re
from dataclasses import dataclass

from posthog.models.team import Team

from products.data_warehouse.backend.types import ExternalDataSourceType
from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

# GitHub source endpoints (``ExternalDataSchema.name``) backing the curated builders. The
# materialized table for each is ``prefix + "github_" + endpoint``, e.g. with prefix
# ``devex_eng_analytics`` the pull-requests table is ``devex_eng_analyticsgithub_pull_requests``.
PULL_REQUESTS_SCHEMA = "pull_requests"
WORKFLOW_RUNS_SCHEMA = "workflow_runs"

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


def resolve_github_tables(*, team: Team) -> GitHubTables:
    """Resolve the team's curated GitHub table names from its warehouse models.

    Picks the oldest connected GitHub source that has both endpoints synced — deterministic
    when a team has more than one GitHub source (e.g. one per repository). Raises
    ``GitHubSourceNotConnectedError`` when no such source exists; the presentation layer
    maps that to a 400 so the UI prompts to connect a source and an agent gets an actionable
    error instead of a misleading empty result.
    """
    sources = (
        ExternalDataSource.objects.filter(team_id=team.pk, source_type=ExternalDataSourceType.GITHUB)
        .exclude(deleted=True)
        .order_by("created_at", "id")
    )
    for source in sources:
        tables = _synced_table_names(team=team, source=source)
        pull_requests = tables.get(PULL_REQUESTS_SCHEMA)
        workflow_runs = tables.get(WORKFLOW_RUNS_SCHEMA)
        if pull_requests and workflow_runs:
            return GitHubTables(pull_requests=pull_requests, workflow_runs=workflow_runs)
    raise GitHubSourceNotConnectedError()


def _synced_table_names(*, team: Team, source: ExternalDataSource) -> dict[str, str]:
    """Map ``{endpoint: table name}`` for a source's actively-synced PR/CI schemas."""
    schemas = (
        ExternalDataSchema.objects.filter(
            team_id=team.pk,
            source_id=source.id,
            should_sync=True,
            name__in=(PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA),
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
