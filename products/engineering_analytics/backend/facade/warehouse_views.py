"""The warehouse views this product exposes, for data_modeling's managed-viewset sync.

data_modeling calls ``get_expected_warehouse_views(team)`` and adapts the returned frozen
contracts into its own ``ExpectedView`` rows (as non-materialized saved queries). Kept behind the
facade so data_modeling never imports this product's read layer directly — it depends only on the
provider-neutral ``ExpectedWarehouseView`` contract.
"""

import posthoganalytics

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import FRICTION_VIEW_FEATURE_FLAG, ExpectedWarehouseView
from products.engineering_analytics.backend.logic.views import ci_failures, ci_job_history, job_costs, pr_friction


def get_expected_warehouse_views(team: Team) -> list[ExpectedWarehouseView]:
    """The team's exposed warehouse views. Empty when the team has no GitHub source with both the
    workflow_runs and workflow_jobs endpoints synced (so no view is created for such teams).

    The three per-job views share that same qualifying-source gate, so they appear together or not at all:
    per-job cost, per-job-attempt history with commit attribution, and fingerprinted CI failure lines.
    The per-PR friction view also needs the pull-request snapshot, and is materialized because replaying
    every pull request's timeline is too heavy to run on each read. It exists only for organizations the
    friction flag targets.
    """
    views: list[ExpectedWarehouseView] = []
    for module in (job_costs, ci_job_history, ci_failures):
        query = module.build_team_view(team)
        if query is not None:
            views.append(ExpectedWarehouseView(name=module.VIEW_NAME, query=query, fields=module.FIELDS))
    friction_query = pr_friction.build_team_view(team) if _friction_view_enabled(team) else None
    if friction_query is not None:
        views.append(
            ExpectedWarehouseView(
                name=pr_friction.VIEW_NAME, query=friction_query, fields=pr_friction.FIELDS, materialized=True
            )
        )
    return views


def _friction_view_enabled(team: Team) -> bool:
    org_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            FRICTION_VIEW_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": org_id, "project": project_id},
            group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )
