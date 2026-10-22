"""Product-analytics requests that agents answer with ``execute-sql`` instead of a typed runner.

Each case reproduces, on Hedgebox, a request shape that the online evaluation
"MCP SQL: typed query runner choice" fails most often on production MCP traces:

- Several metrics in one question ("counts, uniques and a filtered count"), which agents pack
  into one SQL query with ``countIf`` and ``uniqIf`` instead of trends series.
- A count of events that carry a property, a single-day unique-user count, and active users
  without internal accounts, which agents write as SQL with hand-built filters.
- Breakdowns, period comparisons, percentiles, and ratios, which trends expresses with a
  breakdown, ``compareFilter``, property math, and a formula.
- Funnels and return rates computed with ``uniqIf`` per event, which drop the step order and
  conversion window that ``query-funnel`` and ``query-retention`` keep.
- A justified ``system.*`` lookup, followed by an analysis that stays on SQL.

``AnswerFromTypedQuery`` checks which data the answer reports: its values must come from a typed
query result. A SQL query that checks a typed result is allowed, which is looser than the online
judge, because the judge fails any SQL call against event data.
``eval_justified_sql_controls`` holds requests where SQL is the right tool, so a guidance
change that removes these misses cannot pass by sending everything to typed runners.

Run the suites on the latest Claude Opus and GPT Sol models, one runtime per run, and compare
the two runs paired by case:

    hogli evals eval_typed_runner_misses --agent-runtime claude --agent-model claude-opus-5-5 --trials 3
    hogli evals eval_typed_runner_misses --agent-runtime codex --agent-model gpt-6.1-sol --trials 3
"""

from __future__ import annotations

from typing import Unpack

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import AnswerToolCallNot, NoToolCall
from products.posthog_ai.evals.cli_mcp.scorers import FirstRelevantTool
from products.posthog_ai.evals.offline_config import offline_suite
from products.posthog_ai.evals.product_analytics.scorers import (
    INSIGHT_WRITE_TOOLS,
    TYPED_QUERY_TOOLS,
    AnswerFromTypedQuery,
    InsightShape,
    InsightShapeSpec,
)

from .eval_sql_shaped_routing import ANALYSIS_QUERY_TOOLS


def _case(
    name: str, prompt: str, *, first_tool: str | None = None, **shape: Unpack[InsightShapeSpec]
) -> SandboxedEvalCase:
    expected: dict[str, object] = {}
    if first_tool is None:
        expected["answer_from_typed_query"] = {}
    else:
        expected["first_relevant_tool"] = {"tool": first_tool}
    if shape:
        expected["insight_shape"] = shape
    return SandboxedEvalCase(name=name, prompt=prompt, expected=expected)


async def eval_typed_runner_misses(ctx: EvalContext) -> None:
    cases = [
        _case(
            "scorecard_counts_and_uploaders",
            "For the last 7 days, give me the number of uploaded_file events, the number of downloaded_file events, "
            "and how many unique users uploaded a file.",
            tool="query-trends",
            events=["uploaded_file", "downloaded_file", "uploaded_file"],
            math=["total", "dau"],
        ),
        _case(
            "count_with_file_name_present",
            "How many uploaded_file events were there in the last 30 days, and how many of them had a file_name?",
            tool="query-trends",
            events=["uploaded_file", "uploaded_file"],
            filtered_on=["file_name"],
        ),
        _case(
            "unique_signups_yesterday",
            "How many unique users signed up yesterday?",
            tool="query-trends",
            events=["signed_up"],
            math=["dau"],
        ),
        _case(
            "active_users_excluding_internal",
            "What were our weekly and monthly active users over the last 30 days, excluding internal and test "
            "accounts? Count anyone who fired logged_in.",
            tool="query-trends",
            math=["weekly_active", "monthly_active"],
            filter_test_accounts=True,
        ),
        _case(
            "downloads_by_file_type_counts_and_uniques",
            "Break down yesterday's downloaded_file events by file_type, with the event count and the number of "
            "unique users for each type.",
            tool="query-trends",
            breakdown="file_type",
            math=["total", "dau"],
        ),
        _case(
            "uploads_by_os_vs_previous_week",
            "Compare uploaded_file events per operating system over the last 7 days with the 7 days before.",
            tool="query-trends",
            breakdown="$os",
            compare=True,
            events=["uploaded_file"],
        ),
        _case(
            "net_plan_upgrades_formula",
            "What's the net number of plan upgrades minus downgrades per week over the last 8 weeks?",
            tool="query-trends",
            events=["upgraded_plan", "downgraded_plan"],
            formula=True,
        ),
        _case(
            "file_size_percentiles_vs_previous_period",
            "What are the median and 95th percentile file_size_b of uploaded files by file_type over the last 7 "
            "days, compared with the 7 days before?",
            tool="query-trends",
            breakdown="file_type",
            compare=True,
            math=["median", "p95"],
        ),
        _case(
            "pricing_session_share_weekly",
            "What share of weekly sessions with a pageview included a pageview of /pricing/, over the last 8 weeks?",
            tool="query-trends",
            events=["$pageview", "$pageview"],
            math=["unique_session"],
            formula=True,
            filtered_on=["$pathname", "$current_url"],
        ),
        _case(
            "dashboard_tile_signup_funnel",
            "I'm preparing an operations dashboard tile. Compute the 30-day signup funnel: a pageview of /signup/, "
            "then signed_up, then uploaded_file, then upgraded_plan. Don't save anything yet.",
            tool="query-funnel",
            event_sequence=["$pageview", "signed_up", "uploaded_file", "upgraded_plan"],
        ),
        _case(
            "signup_to_upload_last_14_days_vs_prior",
            "Did conversion from signed_up to uploaded_file change in the last 14 days compared with the 14 days "
            "before?",
            tool="query-funnel",
            event_sequence=["signed_up", "uploaded_file"],
        ),
        _case(
            "day1_day7_return_rates",
            "For users who first fired logged_in in the last 30 days, what are their day-1 and day-7 return rates?",
            tool="query-retention",
        ),
        # The system.* lookup is justified SQL and does not count as analytics SQL.
        _case(
            "existing_insight_check_then_query",
            "Check whether we already have a saved insight for weekly logins by browser. If we don't, show me "
            "weekly logged_in counts by $browser over the last 8 weeks.",
            tool="query-trends",
            breakdown="$browser",
            events=["logged_in"],
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-typed-runner-misses-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_typed_runner_misses::eval_typed_runner_misses",
            metrics=[
                "no_persistent_insight_save",
                "answer_from_typed_query",
                "answer_tool_call_not_forbidden",
                "insight_shape",
            ],
        ),
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            AnswerFromTypedQuery(),
            AnswerToolCallNot("execute-sql", TYPED_QUERY_TOOLS),
            InsightShape(),
        ],
        ctx=ctx,
    )


async def eval_justified_sql_controls(ctx: EvalContext) -> None:
    cases = [
        _case(
            "sql_explicit_hogql_request",
            "Write and run a HogQL query that counts uploaded_file events per day over the last 14 days.",
            first_tool="execute-sql",
        ),
        _case(
            "sql_latest_event_timestamp",
            "When did the most recent uploaded_file event arrive? Give me its exact timestamp.",
            first_tool="execute-sql",
        ),
        _case(
            "sql_gap_between_first_and_second_upload",
            "For each user who uploaded a file in the last 30 days, compute the hours between their first and "
            "second uploaded_file event, and show the 10 users with the longest gap.",
            first_tool="execute-sql",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-justified-sql-controls-cli",
        offline_suite=offline_suite(
            "product_analytics/eval_typed_runner_misses::eval_justified_sql_controls",
            metrics=["no_persistent_insight_save", "first_relevant_tool"],
        ),
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS),
        ],
        ctx=ctx,
    )
