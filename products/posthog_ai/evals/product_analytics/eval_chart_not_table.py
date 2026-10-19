"""Does the agent answer a chart-shaped analytics question with a chart, not a Markdown table?

Agents often run the right query and then retype every data point as a Markdown table, or
answer with ``execute-sql``, which has no chart at all. Each case asks a question whose
natural answer is a time series, a breakdown, a funnel, or a retention grid. The agent passes
when the user sees the result as a chart and the final message states the conclusion
without a long table.

``ChartShown`` accepts both chart paths in ``services/mcp/src/templates/render-ui-prompt.md``:
the client shows the query result inline, or the agent calls ``render-ui`` with the same
query tool and input. The ``table_request_keeps_typed_runner`` control asks for a table
explicitly. A table is then a correct answer, but the request alone does not justify SQL.

Run on the latest Claude Opus and GPT Sol models, one runtime per run:

    hogli evals eval_chart_not_table --agent-runtime claude --agent-model claude-opus-5-5 --trials 3
    hogli evals eval_chart_not_table --agent-runtime codex --agent-model gpt-6.1-sol --trials 3
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.cli_mcp.scorers import (
    ChartShown,
    DidNotCiteRawSqlAfterTypedQuery,
    FirstRelevantTool,
    NoMarkdownDataTable,
)
from products.posthog_ai.evals.product_analytics.scorers import INSIGHT_WRITE_TOOLS

from .eval_sql_shaped_routing import ANALYSIS_QUERY_TOOLS


def _chart_case(name: str, prompt: str, tool: str) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "first_relevant_tool": {"tool": tool},
            "chart_shown": {"tool_name_any_of": [tool]},
            "no_markdown_data_table": {},
            "did_not_cite_raw_sql_after_typed_query": {"tool": tool},
        },
    )


async def eval_chart_not_table(ctx: EvalContext) -> None:
    cases = [
        _chart_case(
            "weekly_signups_trend",
            "How have weekly signups changed over the last 12 weeks?",
            "query-trends",
        ),
        _chart_case(
            "daily_uploads_by_file_type",
            "Show daily uploaded_file counts by file_type for the last 30 days.",
            "query-trends",
        ),
        _chart_case(
            "weekly_file_activity_scorecard",
            "Give me weekly uploads, downloads, and deletes for the last 8 weeks.",
            "query-trends",
        ),
        _chart_case(
            "pageviews_by_country",
            "Which countries sent the most pageviews in the last 30 days?",
            "query-trends",
        ),
        _chart_case(
            "pricing_to_upgrade_funnel",
            "What does our funnel from a /pricing/ pageview to signed_up to upgraded_plan look like over the last "
            "30 days?",
            "query-funnel",
        ),
        _chart_case(
            "weekly_signup_retention",
            "How well do users who signed up in the last 8 weeks keep coming back each week?",
            "query-retention",
        ),
        SandboxedEvalCase(
            name="table_request_keeps_typed_runner",
            prompt="List the weekly signup counts for the last 8 weeks as a table.",
            expected={"first_relevant_tool": {"tool": "query-trends"}},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-chart-not-table-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS),
            ChartShown(),
            NoMarkdownDataTable(),
            DidNotCiteRawSqlAfterTypedQuery(),
        ],
        ctx=ctx,
    )
