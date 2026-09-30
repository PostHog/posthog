"""MCP routing evals for prompts that sound like raw SQL requests.

The typed cases ask for trends, funnels, retention, stickiness, or lifecycle
without naming the PostHog analysis. They must call the matching typed runner
rather than ``execute-sql``. The controls require row-level or windowed work,
so they must call ``execute-sql`` without using a typed query runner.

Entity search against the ``system.*`` catalog (e.g. "do we already have an
insight for X?") is a separate failure mode with its own dedicated suite —
see ``retrieval/eval_system_table_search.py`` — and isn't duplicated here.
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.cli_mcp.scorers import FirstRelevantTool
from products.posthog_ai.evals.product_analytics.scorers import INSIGHT_WRITE_TOOLS

ANALYSIS_QUERY_TOOLS = frozenset(
    {"query-trends", "query-funnel", "query-retention", "query-stickiness", "query-lifecycle", "execute-sql"}
)


def _routing_case(*, name: str, prompt: str, target_tool: str) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"first_relevant_tool": {"tool": target_tool}},
    )


async def eval_sql_shaped_typed_query_routing(ctx: EvalContext) -> None:
    """Typed query runners must handle SQL-shaped product-analytics requests."""
    cases = [
        _routing_case(
            name="trends_count_uploaded_files_per_day",
            prompt="Count uploaded_file events per day over the last 30 days",
            target_tool="query-trends",
        ),
        _routing_case(
            name="trends_weekly_signups",
            prompt="Write me a query showing the number of signed_up events per week over the last 8 weeks",
            target_tool="query-trends",
        ),
        _routing_case(
            name="trends_downloads_grouped_by_type",
            prompt="Show downloaded_file events grouped by file_type over the last 30 days",
            target_tool="query-trends",
        ),
        _routing_case(
            name="trends_average_file_size",
            prompt="What is the average file_size_b on uploaded_file events over the last 30 days?",
            target_tool="query-trends",
        ),
        _routing_case(
            name="trends_distinct_logged_in_users",
            prompt="Count distinct users who fired logged_in in the last 7 days",
            target_tool="query-trends",
        ),
        _routing_case(
            name="funnel_signup_to_upload",
            prompt="Of users who fired signed_up, how many went on to fire uploaded_file within a week?",
            target_tool="query-funnel",
        ),
        _routing_case(
            name="funnel_signup_to_upgrade",
            prompt="How many people fired signed_up and then upgraded_plan over the last 30 days?",
            target_tool="query-funnel",
        ),
        _routing_case(
            name="funnel_pricing_to_signup",
            prompt="What share of users who viewed /pricing/ went on to fire signed_up over the last 8 weeks?",
            target_tool="query-funnel",
        ),
        _routing_case(
            name="retention_signup_to_login",
            prompt="Of users who fired signed_up in the last 8 weeks, how many came back to fire logged_in in each of the following weeks?",
            target_tool="query-retention",
        ),
        _routing_case(
            name="retention_repeat_uploads",
            prompt="For users whose first uploaded_file was in the last 8 weeks, how many were still uploading each week after?",
            target_tool="query-retention",
        ),
        _routing_case(
            name="retention_signup_to_login_by_plan",
            prompt="What's the day-1 and day-7 return rate for people who signed up in the last 4 weeks, split by personal vs. business plan?",
            target_tool="query-retention",
        ),
        _routing_case(
            name="trends_multi_series_uploads_and_downloads",
            prompt="Show weekly counts of uploaded_file and downloaded_file side by side over the last 8 weeks",
            target_tool="query-trends",
        ),
        _routing_case(
            name="trends_compare_invited_vs_new_signups",
            prompt="Compare weekly signups from invited team members versus new account signups over the last 8 weeks",
            target_tool="query-trends",
        ),
        _routing_case(
            name="funnel_time_to_first_upload",
            prompt="How long does it typically take someone to upload their first file after signing up?",
            target_tool="query-funnel",
        ),
        _routing_case(
            name="stickiness_weekly_repeat_downloads",
            prompt="Of people who downloaded a file in the last 4 weeks, how many days a week do they typically come back and download again?",
            target_tool="query-stickiness",
        ),
        _routing_case(
            name="lifecycle_pageview_composition",
            prompt="Break last month's active website visitors into new, returning, and lapsed",
            target_tool="query-lifecycle",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-sql-shaped-typed-query-routing-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS),
        ],
        ctx=ctx,
    )


async def eval_sql_shaped_sql_controls(ctx: EvalContext) -> None:
    """SQL-only requests must not be routed through a typed query runner."""
    cases = [
        _routing_case(
            name="sql_list_largest_files",
            prompt="List the 10 largest files by file_size_b from uploaded_file, with their file_name",
            target_tool="execute-sql",
        ),
        _routing_case(
            name="sql_first_and_last_login_per_account",
            prompt="For each account, show the first and last logged_in timestamp",
            target_tool="execute-sql",
        ),
        _routing_case(
            name="sql_median_file_size_by_account",
            prompt="What is the median file_size_b on uploaded_file, and which accounts upload above it?",
            target_tool="execute-sql",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-sql-shaped-sql-controls-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS),
        ],
        ctx=ctx,
    )
