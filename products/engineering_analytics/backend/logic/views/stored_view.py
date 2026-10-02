"""What the stored CI views share: the window of rows they keep, and the source that each row names.

A stored CI view is a materialized view whose rows are the output of a builder the product's reads
use. A rebuild reads every row it stores, so its cost follows the days kept. The views keep what a
page range of ``MAX_STORED_RANGE`` needs.

A view unions every repository of every GitHub source of the team, and a member can be denied some
sources. So each row names the source and the repository it came from.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql.database.models import FieldOrTable, StringDatabaseField
from posthog.hogql.escape_sql import escape_hogql_string

from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    CI_LOOKBACK,
    JOB_FLOOR_SLACK_ON_RUN_STARTED,
)
from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_stored_view_sources

if TYPE_CHECKING:
    from posthog.models.team import Team

MAX_STORED_RANGE = timedelta(days=30)

# A read floors its scan one day below its window, a floor is a whole date, and a table built before
# midnight is read after it. One day for each keeps the stored rows a superset of the rows a read scans.
_FLOOR_MARGIN = timedelta(days=3)

# A read reaches one more span before its range: a timeline also reads the CI from ``CI_LOOKBACK``
# before its range, and a comparison reads the previous period of the same length.
STORED_RUNS_WINDOW = MAX_STORED_RANGE + max(MAX_STORED_RANGE, CI_LOOKBACK) + _FLOOR_MARGIN

# A read that windows the run floors the jobs lower than the runs, by the same slack.
STORED_JOBS_WINDOW = STORED_RUNS_WINDOW + JOB_FLOOR_SLACK_ON_RUN_STARTED

# The runs a stored job can belong to. GitHub ends a workflow run after 35 days, so a run started at
# most that long before any of its jobs was created.
STORED_JOB_RUNS_WINDOW = STORED_JOBS_WINDOW + timedelta(days=35)

# Column order is the saved-query schema: these two come last in every stored CI view.
IDENTITY_FIELDS: dict[str, FieldOrTable] = {
    "source_id": StringDatabaseField(name="source_id"),
    # ``owner/name`` in lower case, or '' for a source that names no repository.
    "repository": StringDatabaseField(name="repository"),
}


def identity_columns(source_id: str, repository: str) -> str:
    """The ``IDENTITY_FIELDS`` columns of a row, as SQL."""
    # GitHub names are case-insensitive, and a source can store them in either case.
    source, repo = escape_hogql_string(str(UUID(source_id))), escape_hogql_string(repository.casefold())
    return f"{source} AS source_id, {repo} AS repository"


def build_source_view(source: JobSourceTables, fields: dict[str, FieldOrTable], rows: str) -> str:
    """One repository's part of a stored CI view: the ``fields`` columns of the ``rows`` query, with
    the source and the repository they came from."""
    columns = ", ".join(name for name in fields if name not in IDENTITY_FIELDS)
    return f"SELECT {columns}, {identity_columns(source.source_id, source.repository)} FROM ({rows})"


def build_team_view(team: "Team", build_source_query: Callable[[JobSourceTables], str]) -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    sources = resolve_stored_view_sources(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(build_source_query(source) for source in sources)
