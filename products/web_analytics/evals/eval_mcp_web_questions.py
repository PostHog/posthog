"""Web analytics questions a customer's agent answers through the PostHog MCP.

Each case asks one question in natural language and is scored two ways: the routing scorer checks the
agent reached for the typed web analytics tool the question calls for, and the answer judge compares the
final message with an oracle the case seeder computes from the seeded project right before the agent runs.

The ``ready_*`` cases ask the ready-made questions in ``ready_prompts.py`` word for word, so a question that stops
working end to end shows up here.
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.scorers import FirstRelevantTool
from products.web_analytics.evals.offline_config import offline_suite
from products.web_analytics.evals.ready_prompts import READY_PROMPTS, render_ready_prompt
from products.web_analytics.evals.scorers import WebAnswerCorrectness
from products.web_analytics.evals.seeders import (
    MIN_LANDING_PAGE_VISITORS,
    SIGNUP_EVENT,
    Seeder,
    seed_ai_agent_traffic,
    seed_audience,
    seed_daily_visitors,
    seed_goal_conversions_by_channel,
    seed_highest_bounce_landing_page,
    seed_signup_conversion_rate,
    seed_signups_by_channel,
    seed_top_channel,
    seed_top_countries,
    seed_top_pages,
    seed_top_referrers,
    seed_traffic_change_drivers,
    seed_traffic_sources,
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


def _case(name: str, prompt: str, tool: str, setup: Seeder, **metadata: str) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        setup=setup,
        expected={"first_relevant_tool": {"tool": tool}},
        metadata={"area": "web_analytics", "tool": tool, **metadata},
    )


# The seeder whose oracle answers each ready-made question, and the arguments the case passes to it.
READY_PROMPT_SEEDERS: dict[str, tuple[Seeder, dict[str, str]]] = {
    "web-analytics-weekly-summary": (seed_weekly_digest, {}),
    "web-analytics-traffic-change": (seed_traffic_change_drivers, {}),
    "web-analytics-compare-periods": (seed_week_over_week, {}),
    "web-analytics-yesterday-vs-last-week": (seed_yesterday_vs_last_week, {}),
    "web-analytics-top-pages": (seed_top_pages, {}),
    "web-analytics-traffic-sources": (seed_traffic_sources, {}),
    "web-analytics-worst-bounce-landing-pages": (seed_highest_bounce_landing_page, {}),
    "web-analytics-goal-conversion-rate": (seed_signup_conversion_rate, {"goal": SIGNUP_EVENT}),
    "web-analytics-goal-conversion-by-channel": (seed_goal_conversions_by_channel, {"goal": SIGNUP_EVENT}),
    "web-analytics-worst-web-vitals": (seed_web_vitals, {}),
    "web-analytics-ai-agent-traffic": (seed_ai_agent_traffic, {}),
    "web-analytics-audience": (seed_audience, {}),
    "web-analytics-daily-visitors": (seed_daily_visitors, {}),
}


def _ready_prompt_cases() -> list[SandboxedEvalCase]:
    cases = []
    for prompt in READY_PROMPTS:
        seeder, arguments = READY_PROMPT_SEEDERS[prompt.name]
        cases.append(
            _case(
                f"ready_{prompt.name.removeprefix('web-analytics-').replace('-', '_')}",
                render_ready_prompt(prompt, arguments),
                prompt.tools[0],
                seeder,
                ready_prompt=prompt.name,
            )
        )
    return cases


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
    *_ready_prompt_cases(),
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
