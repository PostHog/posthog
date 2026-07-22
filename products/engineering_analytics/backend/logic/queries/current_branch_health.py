"""Current default-branch CI verdict over the fixed recent-health window."""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import CurrentBranchHealth
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import LATEST_COMPLETED_RUN_FAILED

_FAILING_NAME_LIMIT = 20

_SELECT = f"""
    SELECT
        workflow_name,
        countIf(status = 'completed') AS completed_count,
        {LATEST_COMPLETED_RUN_FAILED} AS latest_failed
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} AND head_branch = {{branch}}
    GROUP BY workflow_name
"""


def query_current_branch_health(
    *, curated: CuratedGitHubSource, date_from: datetime, branch: str
) -> CurrentBranchHealth:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.current_branch_health",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "branch": ast.Constant(value=branch),
        },
    )

    settled_workflows = 0
    failing_workflow_names: list[str] = []
    for workflow_name, completed_count, latest_failed in response.results or []:
        # Nothing completed yet: not settled, and LATEST_COMPLETED_RUN_FAILED's 0 default would read as passing.
        if not completed_count:
            continue
        settled_workflows += 1
        if latest_failed:
            failing_workflow_names.append(workflow_name)

    failing_workflow_names.sort()
    return CurrentBranchHealth(
        default_branch=branch,
        settled_workflows=settled_workflows,
        failing_workflows=len(failing_workflow_names),
        failing_workflow_names=failing_workflow_names[:_FAILING_NAME_LIMIT],
    )
