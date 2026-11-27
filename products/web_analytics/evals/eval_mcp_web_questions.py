"""Web analytics questions a customer's agent answers through the PostHog MCP.

Each case asks one question in natural language and is scored two ways: the routing scorer checks the
agent reached for the typed web analytics tool the question calls for, and the answer judge compares the
final message with an oracle the case seeder computes from the seeded project right before the agent runs.
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.scorers import FirstRelevantTool
from products.web_analytics.evals.offline_config import offline_suite
from products.web_analytics.evals.scorers import WebAnswerCorrectness
from products.web_analytics.evals.seeders import (
    MIN_LANDING_PAGE_VISITORS,
    Seeder,
    seed_daily_visitors,
    seed_highest_bounce_landing_page,
    seed_signup_conversion_rate,
    seed_signups_by_channel,
    seed_top_channel,
    seed_top_countries,
    seed_top_pages,
    seed_top_referrers,
    seed_unique_visitors,
    seed_web_vitals,
    seed_week_over_week,
    seed_weekly_digest,
    seed_yesterday_vs_last_week,
)

WEB_TOOLS = frozenset(
    {
        "query-web-overview",
        "query-web-stats",
        "query-web-vitals",
        "web-analytics-weekly-digest",
        "query-trends",
        "execute-sql",
    }
)


def _case(name: str, prompt: str, tool: str, setup: Seeder) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        setup=setup,
        expected={"first_relevant_tool": {"tool": tool}},
        metadata={"area": "web_analytics", "tool": tool},
    )


CASES = [
    _case(
        "unique_visitors_7d",
        "How many unique visitors did the site get in the last 7 days?",
        "query-web-overview",
        seed_unique_visitors,
    ),
    _case(
        "top_pages_7d",
        "What were the top 5 pages by visitors in the last 7 days?",
        "query-web-stats",
        seed_top_pages,
    ),
    _case(
        "highest_bounce_landing_page",
        f"Which landing page with at least {MIN_LANDING_PAGE_VISITORS} visitors has the highest bounce rate over the last 7 days?",
        "query-web-stats",
        seed_highest_bounce_landing_page,
    ),
    _case(
        "week_over_week",
        "How does traffic over the last 7 days compare with the 7 days before?",
        "query-web-overview",
        seed_week_over_week,
    ),
    _case(
        "top_channel_7d",
        "Which marketing channel brought the most traffic in the last 7 days?",
        "query-web-stats",
        seed_top_channel,
    ),
    _case(
        "signups_by_channel_7d",
        "Which channel brought the most sign-ups in the last 7 days, and how many?",
        "query-web-stats",
        seed_signups_by_channel,
    ),
    _case(
        "top_countries_7d",
        "Which countries do most of our visitors come from?",
        "query-web-stats",
        seed_top_countries,
    ),
    _case(
        "top_referrers_7d",
        "Which referring domains send us the most visitors, over the last 7 days?",
        "query-web-stats",
        seed_top_referrers,
    ),
    _case(
        "signup_conversion_rate_7d",
        "What share of visitors signed up in the last 7 days?",
        "query-web-overview",
        seed_signup_conversion_rate,
    ),
    _case(
        "yesterday_vs_same_day_last_week",
        "How did yesterday compare with the same day last week for sessions and session duration?",
        "query-web-overview",
        seed_yesterday_vs_last_week,
    ),
    _case(
        "worst_lcp_pages",
        "Which pages have the worst Largest Contentful Paint over the last 7 days?",
        "query-web-vitals",
        seed_web_vitals,
    ),
    _case(
        "daily_visitors_14d",
        "Show daily unique visitors for the last 14 days.",
        "query-trends",
        seed_daily_visitors,
    ),
    _case(
        "weekly_digest",
        "How did the website do last week?",
        "web-analytics-weekly-digest",
        seed_weekly_digest,
    ),
]


async def eval_mcp_web_questions(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-web-analytics-mcp-questions-cli",
        offline_suite=offline_suite(
            "web_analytics/eval_mcp_web_questions::eval_mcp_web_questions",
            metrics=["first_relevant_tool", "web_answer_correctness"],
        ),
        cases=CASES,
        scorers=[FirstRelevantTool(relevant_tools=WEB_TOOLS), WebAnswerCorrectness()],
        ctx=ctx,
        send_to_posthog=True,
    )
