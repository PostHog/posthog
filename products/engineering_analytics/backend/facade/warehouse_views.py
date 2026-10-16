"""The warehouse views this product exposes, for data_modeling's managed-viewset sync.

data_modeling calls ``get_expected_warehouse_views(team)`` and adapts the returned frozen
contracts into its own ``ExpectedView`` rows (as non-materialized saved queries). Kept behind the
facade so data_modeling never imports this product's read layer directly — it depends only on the
provider-neutral ``ExpectedWarehouseView`` contract.
"""

import posthoganalytics

from posthog.hogql.database.models import FieldOrTable

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.engineering_analytics.backend.facade.contracts import (
    MATERIALIZED_VIEWS_FEATURE_FLAG,
    ExpectedWarehouseView,
)
from products.engineering_analytics.backend.logic.views import (
    ci_failures,
    ci_job_history,
    ci_rows,
    job_costs,
    pr_friction,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind


def get_expected_warehouse_views(team: Team) -> list[ExpectedWarehouseView]:
    """The team's exposed warehouse views. Empty when the team has no GitHub source with both the
    workflow_runs and workflow_jobs endpoints synced, so they appear together or not at all. The
    materialized views spend the team's warehouse compute, so they exist only for organizations the
    flag targets.
    """
    views: list[ExpectedWarehouseView] = []
    for module in (job_costs, ci_job_history, ci_failures):
        query = module.build_team_view(team)
        if query is not None:
            views.append(ExpectedWarehouseView(name=module.VIEW_NAME, query=query, fields=module.FIELDS))
    if not views or not _materialized_views_enabled(team):
        return views
    if stored := ci_rows.build_team_views(team):
        runs_query, jobs_query = stored
        views.append(_stored_view(ci_rows.RUNS_VIEW_NAME, runs_query, ci_rows.RUN_FIELDS))
        views.append(_stored_view(ci_rows.JOBS_VIEW_NAME, jobs_query, ci_rows.JOB_FIELDS))
    friction_query = pr_friction.build_team_view(team)
    if friction_query is not None:
        views.append(
            ExpectedWarehouseView(
                name=pr_friction.VIEW_NAME, query=friction_query, fields=pr_friction.FIELDS, materialized=True
            )
        )
    return views


def _stored_view(name: str, query: str, fields: dict[str, FieldOrTable]) -> ExpectedWarehouseView:
    return ExpectedWarehouseView(
        name=name,
        query=query,
        fields=fields,
        materialized=True,
        sync_frequency=ci_rows.SYNC_FREQUENCY,
        incremental_config=ci_rows.INCREMENTAL_CONFIG,
    )


def _materialized_views_enabled(team: Team) -> bool:
    org_id = str(team.organization_id)
    project_id = str(team.id)
    enabled = posthoganalytics.feature_enabled(
        MATERIALIZED_VIEWS_FEATURE_FLAG,
        str(team.uuid),
        groups={"organization": org_id, "project": project_id},
        group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if enabled is None:
        # No answer (the flag service failed, or the flag does not exist). The sync deletes every view it
        # does not expect, so keep the views the team has rather than drop a materialized table on an outage.
        return (
            # Only this product's managed view counts: a user's own saved query can carry the same name.
            DataWarehouseSavedQuery.objects.filter(
                team_id=team.id,
                name__in=(pr_friction.VIEW_NAME, ci_rows.RUNS_VIEW_NAME, ci_rows.JOBS_VIEW_NAME),
                managed_viewset__kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
            )
            .exclude(deleted=True)
            .exists()
        )
    return enabled
