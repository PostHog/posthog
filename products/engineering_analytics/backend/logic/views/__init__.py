"""The engineering_analytics curated HogQL read layer.

Two per-team views over the GitHub warehouse snapshots — the single substrate
every surface (the SQL/MCP query tool, the ``pr_lifecycle`` deep tool, the future
UI) reads from. All PR/CI domain rules (bot detection, repo identity, label
extraction, the head-SHA CI join, honest metric naming) are defined here exactly
once. ``orchestrator.build_all_engineering_analytics_views`` is the entry point
the core HogQL database calls per team.
"""

from products.engineering_analytics.backend.logic.views.pull_requests import VIEW_NAME as PULL_REQUESTS_VIEW
from products.engineering_analytics.backend.logic.views.workflow_runs import VIEW_NAME as WORKFLOW_RUNS_VIEW

__all__ = ["PULL_REQUESTS_VIEW", "WORKFLOW_RUNS_VIEW"]
