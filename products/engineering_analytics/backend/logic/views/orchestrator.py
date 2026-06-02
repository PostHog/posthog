"""Per-team assembly of the engineering_analytics read layer.

``build_all_engineering_analytics_views`` is the entry point the core HogQL
database calls (via the facade) when constructing a team's ``Database``. It
returns the curated views only for the source tables the team actually has, so
teams without the GitHub warehouse source get nothing rather than views that
error on first ``SELECT``.
"""

from collections.abc import Callable

from posthog.hogql.database.models import SavedQuery

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs
from products.warehouse_sources.backend.models.table import DataWarehouseTable

# (view builder, source warehouse table it reads from)
_BUILDERS: tuple[tuple[Callable[[], SavedQuery], str], ...] = (
    (pull_requests.build_view, pull_requests.SOURCE_TABLE),
    (workflow_runs.build_view, workflow_runs.SOURCE_TABLE),
)


def build_all_engineering_analytics_views(team: Team) -> list[SavedQuery]:
    source_tables = [source_table for _, source_table in _BUILDERS]
    present = set(
        DataWarehouseTable.raw_objects.filter(team_id=team.pk, name__in=source_tables)
        .exclude(deleted=True)
        .values_list("name", flat=True)
    )
    return [build_view() for build_view, source_table in _BUILDERS if source_table in present]
