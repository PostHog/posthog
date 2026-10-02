"""What the stored CI views share: the window of rows they keep, the source that each row names, and
how a read takes the rows back.

A stored CI view is a materialized view whose rows are the output of a builder the product's reads
use. A rebuild reads every row it stores, so its cost follows the days kept. The views keep what a
page range of 30 days needs, and a longer range reads the raw tables.

A view unions every repository of every GitHub source of the team, and a member can be denied some
sources. So each row names the source and the repository it came from, and a read takes the rows of
the one pair it resolved.
"""

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql.database.models import BooleanDatabaseField, DatabaseField, FieldOrTable, StringDatabaseField
from posthog.hogql.escape_sql import escape_hogql_string

from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    CI_LOOKBACK,
    JOB_FLOOR_SLACK_ON_RUN_STARTED,
)
from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_stored_view_sources

if TYPE_CHECKING:
    from posthog.models.team import Team

_LONGEST_STORED_RANGE = timedelta(days=30)

# A read floors its scan one day below its window, a floor is a whole date, and a table built before
# midnight is read after it. One day for each keeps the stored rows a superset of the rows a read scans.
_FLOOR_MARGIN = timedelta(days=3)

# A read reaches one more span before its range: a timeline also reads the CI from ``CI_LOOKBACK``
# before its range, and a comparison reads the previous period of the same length.
STORED_RUNS_WINDOW = _LONGEST_STORED_RANGE + max(_LONGEST_STORED_RANGE, CI_LOOKBACK) + _FLOOR_MARGIN

STORED_JOBS_WINDOW = STORED_RUNS_WINDOW + JOB_FLOOR_SLACK_ON_RUN_STARTED

# The runs a stored job can belong to. GitHub ends a workflow run after 35 days, so a run started at
# most that long before any of its jobs was created.
STORED_JOB_RUNS_WINDOW = STORED_JOBS_WINDOW + timedelta(days=35)

IDENTITY_FIELDS: dict[str, FieldOrTable] = {
    "source_id": StringDatabaseField(name="source_id"),
    "repository": StringDatabaseField(name="repository"),
}


def _source_literal(source_id: str) -> str:
    return escape_hogql_string(str(UUID(source_id)))


def _repository_literal(repository: str) -> str:
    # GitHub names are case-insensitive, and a source can store them in either case.
    return escape_hogql_string(repository.casefold())


def identity_columns(source_id: str, repository: str) -> str:
    """The ``IDENTITY_FIELDS`` columns of a row, as SQL. ``repository`` is ``owner/name`` in lower
    case, or '' for a source that names no repository."""
    return f"{_source_literal(source_id)} AS source_id, {_repository_literal(repository)} AS repository"


def build_source_view(source: JobSourceTables, columns: Iterable[str], rows: str) -> str:
    """One repository's part of a stored CI view: the ``columns`` of the ``rows`` query, then the
    source and the repository they came from."""
    return f"SELECT {', '.join(columns)}, {identity_columns(source.source_id, source.repository)} FROM ({rows})"


def build_team_view(team: "Team", build_source_query: Callable[[JobSourceTables], str]) -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    sources = resolve_stored_view_sources(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(build_source_query(source) for source in sources)


def lowest_stored_date(built_at: datetime, window: timedelta) -> str:
    """The lowest date-only scan floor that a table built at ``built_at`` answers in full. The view's
    own floor sits a day lower, which covers a rebuild that read the clock shortly before or after
    ``built_at`` was recorded."""
    return (built_at - window).strftime("%Y-%m-%d")


def stored_rows(view_name: str, *, source_id: str, repository: str) -> str:
    """The stored rows of one repository of one source, as a subquery."""
    return (
        f"(SELECT * FROM {view_name} WHERE source_id = {_source_literal(source_id)} "
        f"AND repository = {_repository_literal(repository)})"
    )


def stored_column(name: str, field: FieldOrTable, *, stored_as: str | None = None) -> str:
    """SQL that reads the stored column ``stored_as`` as ``name``, with the type the view declares.

    A materialized table makes every column nullable and stores a boolean as an integer. A read must
    get the builder's types back, or a predicate and an aggregate behave differently than on the raw
    tables.
    """
    column = stored_as or name
    if not isinstance(field, DatabaseField) or field.is_nullable():
        return column if column == name else f"{column} AS {name}"
    restored = f"assumeNotNull({column})"
    if isinstance(field, BooleanDatabaseField):
        restored = f"{restored} != 0"
    return f"{restored} AS {name}"
