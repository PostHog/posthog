"""Does an agent use the Self-driving inbox the way a person would want?

The inbox exists so that a person knows what is going on in their product without checking it by hand. These
suites run an agent against a project whose inbox already holds researched reports, and score whether the agent
goes there, how cheaply it reads a report, and what it does when asked to implement one.

* ``eval_inbox_jtbd``: an open question about the product must reach the inbox. Other tools are optional.
* ``eval_inbox_lookup``: a report is pulled for an error tracking issue, read within a budget of tool calls,
  output and time, and found through search or SQL.
* ``eval_inbox_implementation``: implementing a report claims it, drafts a pull request that links the report
  as the Self-driving report with evidence, and proposes an automation. Eval runs cannot publish, so the case
  asks for the draft in the answer.

The inbox line in the MCP instructions is behind a feature flag. Run the suites once with it and once without
to see what the line changes. Eval runs resolve every other MCP flag to false, so also turn on the inbox search::

    EVAL_MCP_FLAG_OVERRIDES='{"inbox-reports-search": true}' hogli evals signals/eval_inbox_consumer
    EVAL_MCP_FLAG_OVERRIDES='{"inbox-reports-search": true, "self-driving-mcp-instructions-nudge": "line-with-count"}' \\
        hogli evals signals/eval_inbox_consumer
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.services import run_mcp_flag_overrides

from .inbox_consumer_fixture import (
    CHECKOUT_TIMEOUT,
    FIREFOX_UPLOAD_DROP,
    FOR_USER_REPORTS,
    PDF_PREVIEW,
    UPLOAD_COUNTED_EARLY,
    status_counts,
)
from .inbox_consumer_scorers import (
    AnswerStatesFact,
    AnswerSurfacesReports,
    AutomationProposed,
    FoundThroughSearchOrSql,
    InboxRead,
    InboxSqlRan,
    PullRequestFramesReport,
    PullRequestLinksReport,
    ReportClaimed,
    ReportPulled,
    WithinBudget,
)
from .inbox_consumer_seeders import seed_inbox


def _case(name: str, prompt: str, expected: dict[str, Any]) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected=expected,
        setup=seed_inbox,
        metadata={"mcp_flag_overrides": run_mcp_flag_overrides()},
    )


async def eval_inbox_jtbd(ctx: EvalContext) -> None:
    surfaces_reports = {
        "inbox_read": {},
        "answer_surfaces_reports": {"reports": [report.title for report in FOR_USER_REPORTS]},
    }
    await SandboxedEval(
        experiment_name="sandboxed-inbox-jtbd-cli",
        cases=[
            _case("whats_going_on", "I want to know what's going on in my product.", surfaces_reports),
            _case("needs_attention", "What needs my attention today?", surfaces_reports),
            _case("anything_broken", "Did anything break for our users this week?", surfaces_reports),
        ],
        scorers=[InboxRead(), AnswerSurfacesReports()],
        ctx=ctx,
    )


async def eval_inbox_lookup(ctx: EvalContext) -> None:
    counts = ", ".join(f"{status} {count}" for status, count in sorted(status_counts().items()))
    await SandboxedEval(
        experiment_name="sandboxed-inbox-lookup-cli",
        cases=[
            # The exception names the timeout but not its cause. Only the report gives the cause and the fix.
            _case(
                "error_issue_from_inbox",
                "Why do plan upgrades keep failing with the checkout TimeoutError, and how should we fix it?",
                {
                    "report_pulled": {"report": CHECKOUT_TIMEOUT.key},
                    "answer_states_fact": {"fact": CHECKOUT_TIMEOUT.planted_fact},
                },
            ),
            # The suggested fix sits below the summary's first heading, so the list row alone cannot answer.
            _case(
                "report_read_cheaply",
                "Open the inbox report about new Firefox users and their first upload. What does it suggest we do?",
                {
                    "report_pulled": {"report": FIREFOX_UPLOAD_DROP.key},
                    "answer_states_fact": {"fact": FIREFOX_UPLOAD_DROP.planted_fact},
                    "tool_calls_within_budget": {"max": 4},
                    "tool_output_chars_within_budget": {"max": 20_000},
                    "tool_seconds_within_budget": {"max": 60},
                },
            ),
            _case(
                "report_found_by_search",
                "Do we already have an inbox report about PDF previews that fail to render?",
                {
                    "found_through_search_or_sql": {"report": PDF_PREVIEW.key},
                    "answer_states_fact": {"fact": f"An inbox report covers it: {PDF_PREVIEW.title}."},
                },
            ),
            _case(
                "reports_counted_by_sql",
                "Use SQL to count our inbox reports by status, and give me the numbers.",
                {
                    "inbox_sql_ran": {},
                    "answer_states_fact": {"fact": f"The number of inbox reports in each status: {counts}."},
                },
            ),
        ],
        scorers=[
            ReportPulled(),
            FoundThroughSearchOrSql(),
            InboxSqlRan(),
            AnswerStatesFact(),
            WithinBudget("tool_calls"),
            WithinBudget("tool_output_chars"),
            WithinBudget("tool_seconds"),
        ],
        ctx=ctx,
    )


async def eval_inbox_implementation(ctx: EvalContext) -> None:
    report = {"report": UPLOAD_COUNTED_EARLY.key}
    await SandboxedEval(
        experiment_name="sandboxed-inbox-implementation-cli",
        cases=[
            _case(
                "implement_report",
                "Implement the inbox report about uploads that are counted before they finish. Then give me the "
                "title and description of the pull request you would open for it.",
                {
                    "report_pulled": report,
                    "report_claimed": report,
                    "pull_request_links_report": report,
                    "pull_request_frames_report": report,
                    "automation_proposed": {},
                },
            ),
            _case(
                "fixable_reports",
                "Which of my inbox reports could an agent fix right away?",
                {"inbox_read": {}, "automation_proposed": {}},
            ),
        ],
        scorers=[
            InboxRead(),
            ReportPulled(),
            ReportClaimed(),
            PullRequestLinksReport(),
            PullRequestFramesReport(),
            AutomationProposed(),
        ],
        ctx=ctx,
    )
