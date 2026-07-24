"""Orchestration for engineering_analytics.

Resolves caller inputs (PostHog-convention date strings, ``owner/name`` repo) and binds the
team to its curated GitHub read layer (``CuratedGitHubSource``, which resolves the warehouse
table names), then returns canonical contract types. The curated query builders
(``backend/logic/views``) own all GitHub-shaped mapping and domain rules; this layer deals
only in canonical types.

Implementation lives in one module per surface area, mirroring ``presentation/views``; this
package namespace is the layer's interface and re-exports the full builder surface for the
facade.
"""

# Each builder operates on an already-resolved CuratedGitHubSource: source selection and per-source
# warehouse access control happen once at the facade, which hands these builders the authorized
# handle. They validate their own inputs (dates, repo) and read PR/CI data through the handle.
from products.engineering_analytics.backend.logic.ci_signals_config import (
    get_ci_signals_config as get_ci_signals_config,
    update_ci_signals_config as update_ci_signals_config,
)
from products.engineering_analytics.backend.logic.pull_requests import (
    build_author_workflow_costs as build_author_workflow_costs,
    build_ci_cards as build_ci_cards,
    build_ci_failure_logs as build_ci_failure_logs,
    build_pr_cost as build_pr_cost,
    build_pr_lifecycle as build_pr_lifecycle,
    build_pr_runs as build_pr_runs,
    build_pull_request_list as build_pull_request_list,
    build_resolve_branch as build_resolve_branch,
)
from products.engineering_analytics.backend.logic.quarantine import (
    build_quarantine as build_quarantine,
    request_quarantine as request_quarantine,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource as CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import build_github_sources as build_github_sources
from products.engineering_analytics.backend.logic.suite_health import (
    build_broken_tests as build_broken_tests,
    build_flaky_tests as build_flaky_tests,
)
from products.engineering_analytics.backend.logic.teams import (
    build_team_ci_activity as build_team_ci_activity,
    build_team_ci_health as build_team_ci_health,
    build_team_merge_trend as build_team_merge_trend,
)
from products.engineering_analytics.backend.logic.workflows import (
    build_current_branch_health as build_current_branch_health,
    build_job_aggregates as build_job_aggregates,
    build_master_failures as build_master_failures,
    build_repo_overview as build_repo_overview,
    build_repo_run_activity as build_repo_run_activity,
    build_run_failure_logs as build_run_failure_logs,
    build_workflow_health as build_workflow_health,
    build_workflow_jobs as build_workflow_jobs,
    build_workflow_run as build_workflow_run,
    build_workflow_run_activity as build_workflow_run_activity,
    build_workflow_run_list as build_workflow_run_list,
    build_workflow_runner_costs as build_workflow_runner_costs,
)
