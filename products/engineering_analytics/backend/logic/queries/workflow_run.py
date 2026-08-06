"""HogQL assembly of a single workflow run, for the run detail page.

Embeds the curated ``github_workflow_runs`` builder as a subquery (via ``_curated``) and selects one
run by its GitHub Actions ``id``. Run-level only — per-job/step data isn't in the warehouse yet. A run
can have multiple attempts (re-runs) sharing the same id; the latest attempt is the canonical row.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._run_detail import RUN_DETAIL_COLUMNS, to_run_detail

_SELECT = f"""
    SELECT
        {RUN_DETAIL_COLUMNS}
    FROM __RUNS_SOURCE__ AS r
    WHERE id = {{run_id}}
    ORDER BY run_attempt DESC
    LIMIT 1
"""


def query_workflow_run(*, curated: CuratedGitHubSource, run_id: int) -> WorkflowRunDetail | None:
    response = curated.run(
        _SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.workflow_run",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    if not response.results:
        return None
    return to_run_detail(response.results[0])
