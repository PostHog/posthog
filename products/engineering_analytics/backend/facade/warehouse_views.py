"""The warehouse views this product exposes, for data_modeling's managed-viewset sync.

data_modeling calls ``get_expected_warehouse_views(team)`` and adapts the returned frozen
contracts into its own ``ExpectedView`` rows. Kept behind the facade so data_modeling never
imports this product's read layer directly. It depends only on the provider-neutral
``ExpectedWarehouseView`` contract.
"""

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    MATERIALIZED_VIEWS_FEATURE_FLAG,
    ExpectedWarehouseView,
)
from products.engineering_analytics.backend.logic.feature_flags import team_flag
from products.engineering_analytics.backend.logic.stored_views import STORED_VIEWS, managed_views
from products.engineering_analytics.backend.logic.views import ci_failures, ci_job_history, job_costs, pr_friction

_QUERY_TIME_VIEWS = (job_costs, ci_job_history, ci_failures)
_MATERIALIZED_VIEWS = (*STORED_VIEWS, pr_friction)


def get_expected_warehouse_views(team: Team) -> list[ExpectedWarehouseView]:
    """The team's exposed warehouse views. Empty when the team has no GitHub source with both the
    workflow_runs and workflow_jobs endpoints synced (so no view is created for such teams).

    The three per-job views share that same qualifying-source gate, so they appear together or not at all:
    per-job cost, per-job-attempt history with commit attribution, and fingerprinted CI failure lines.
    They are computed at query time.

    The materialized views exist only for organizations the materialized-views flag targets: the two
    stored CI views, and the per-PR friction, which also needs the pull-request snapshot and is too
    heavy to replay on each read.
    """
    modules = _QUERY_TIME_VIEWS + (_MATERIALIZED_VIEWS if _materialized_views_enabled(team) else ())
    views: list[ExpectedWarehouseView] = []
    for module in modules:
        query = module.build_team_view(team)
        if query is not None:
            views.append(
                ExpectedWarehouseView(
                    name=module.VIEW_NAME,
                    query=query,
                    fields=module.FIELDS,
                    materialized=module in _MATERIALIZED_VIEWS,
                )
            )
    return views


def _materialized_views_enabled(team: Team) -> bool:
    enabled = team_flag(MATERIALIZED_VIEWS_FEATURE_FLAG, team)
    if enabled is None:
        # No answer (the flag service failed, or the flag does not exist). The sync deletes every view it
        # does not expect, so keep the views the team has rather than drop a materialized table on an outage.
        return managed_views(team.id, [module.VIEW_NAME for module in _MATERIALIZED_VIEWS]).exists()
    return enabled
