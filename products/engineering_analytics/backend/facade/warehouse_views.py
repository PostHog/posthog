"""The warehouse views this product exposes, for data_modeling's managed-viewset sync.

data_modeling calls ``get_expected_warehouse_views(team)`` and adapts the returned frozen
contracts into its own ``ExpectedView`` rows (as non-materialized saved queries). Kept behind the
facade so data_modeling never imports this product's read layer directly — it depends only on the
provider-neutral ``ExpectedWarehouseView`` contract.
"""

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import ExpectedWarehouseView
from products.engineering_analytics.backend.logic.views import ci_failures, ci_job_history, job_costs


def get_expected_warehouse_views(team: Team) -> list[ExpectedWarehouseView]:
    """The team's exposed warehouse views. Empty when the team has no GitHub source with both the
    workflow_runs and workflow_jobs endpoints synced (so no view is created for such teams).

    All three views share that same qualifying-source gate, so they appear together or not at all:
    per-job cost, per-job-attempt history with commit attribution, and fingerprinted CI failure lines.
    """
    views: list[ExpectedWarehouseView] = []
    for module in (job_costs, ci_job_history, ci_failures):
        query = module.build_team_view(team)
        if query is not None:
            views.append(ExpectedWarehouseView(name=module.VIEW_NAME, query=query, fields=module.FIELDS))
    return views
