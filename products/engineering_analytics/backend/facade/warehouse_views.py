"""The warehouse views this product exposes, for data_modeling's managed-viewset sync.

data_modeling calls ``get_expected_warehouse_views(team)`` and adapts the returned frozen
contracts into its own ``ExpectedView`` rows. Kept behind the facade so data_modeling never
imports this product's read layer directly. It depends only on the provider-neutral
``ExpectedWarehouseView`` contract.
"""

import posthoganalytics

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.engineering_analytics.backend.facade.contracts import (
    MATERIALIZED_VIEWS_FEATURE_FLAG,
    ExpectedWarehouseView,
)
from products.engineering_analytics.backend.logic.views import (
    ci_failures,
    ci_job_history,
    ci_jobs,
    ci_runs,
    job_costs,
    pr_friction,
)
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

_QUERY_TIME_VIEWS = (job_costs, ci_job_history, ci_failures)
_MATERIALIZED_VIEWS = (ci_runs, ci_jobs, pr_friction)


def get_expected_warehouse_views(team: Team) -> list[ExpectedWarehouseView]:
    """The team's exposed warehouse views. Empty when the team has no GitHub source with both the
    workflow_runs and workflow_jobs endpoints synced (so no view is created for such teams).

    The three per-job views share that same qualifying-source gate, so they appear together or not at all:
    per-job cost, per-job-attempt history with commit attribution, and fingerprinted CI failure lines.
    They are computed at query time.

    The materialized views exist only for organizations the materialized-views flag targets: the CI
    runs and the CI jobs as stored tables for the product's own reads, and the per-PR friction, which
    also needs the pull-request snapshot and is too heavy to replay on each read.
    """
    modules = [(module, False) for module in _QUERY_TIME_VIEWS]
    if _materialized_views_enabled(team):
        modules += [(module, True) for module in _MATERIALIZED_VIEWS]
    views: list[ExpectedWarehouseView] = []
    for module, materialized in modules:
        query = module.build_team_view(team)
        if query is not None:
            views.append(
                ExpectedWarehouseView(
                    name=module.VIEW_NAME, query=query, fields=module.FIELDS, materialized=materialized
                )
            )
    return views


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
            # Only this product's managed views count: a user's own saved query can carry the same name.
            DataWarehouseSavedQuery.objects.filter(
                team_id=team.id,
                name__in=[module.VIEW_NAME for module in _MATERIALIZED_VIEWS],
                managed_viewset__kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
            )
            .exclude(deleted=True)
            .exists()
        )
    return enabled
