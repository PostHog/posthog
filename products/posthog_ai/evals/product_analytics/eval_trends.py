"""Product analytics trends eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_trends.py`` — the CI version asserts
on the exact ``AssistantTrendsQuery`` Max produces, this version exercises
the same intents end-to-end through the sandboxed agent + PostHog MCP tools
and judges the trends query the agent ran via the ``query-trends`` MCP tool.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_trends"
"""

from __future__ import annotations

from datetime import datetime

from posthog.schema import (
    AssistantEventMultipleBreakdownFilterType,
    AssistantGenericMultipleBreakdownFilter,
    AssistantTrendsBreakdownFilter,
    AssistantTrendsEventsNode,
    AssistantTrendsFilter,
    AssistantTrendsQuery,
    TrendsFormulaNode,
)

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import LastToolCallNot, NoToolCall
from products.posthog_ai.evals.product_analytics.scorers import (
    INSIGHT_WRITE_TOOLS,
    TrendsSchemaAlignment,
    TrendsTimeRangeRelevancy,
)
from products.posthog_ai.evals.retrieval.scorers import SkillLoaded


def _trends_case(
    *,
    name: str,
    prompt: str,
    query: AssistantTrendsQuery,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "trends_query": query.model_dump(exclude_none=True, mode="json"),
        },
    )


async def eval_trends(ctx: EvalContext) -> None:
    cases = [
        _trends_case(
            name="trends_pageview_default",
            prompt="Show the $pageview trend",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="$pageview",
                        math="total",
                        properties=None,
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_mau",
            prompt="What is our MAU?",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                trendsFilter=AssistantTrendsFilter(
                    display="BoldNumber",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event=None,
                        math="dau",  # "dau" name is a legacy misnomer, it actually just means "unique users"
                        properties=None,
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_chrome_vs_safari_upload",
            prompt="can you compare how many Chrome vs Safari users uploaded a file in the last 30d?",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                breakdownFilter=AssistantTrendsBreakdownFilter(
                    breakdowns=[
                        AssistantGenericMultipleBreakdownFilter(
                            property="$browser",
                            type=AssistantEventMultipleBreakdownFilterType.EVENT,
                        )
                    ]
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="uploaded_file",
                        math="total",
                        properties=[
                            {
                                "key": "$browser",
                                "value": ["Chrome", "Safari"],
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_identify_over_pageview_ratio",
            prompt="i want to see a ratio of identify divided by page views",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph", showLegend=True, formulaNodes=[TrendsFormulaNode(formula="A/B")]
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="$identify",
                        math="total",
                        properties=None,
                    ),
                    AssistantTrendsEventsNode(
                        event="$pageview",
                        math="total",
                        properties=None,
                    ),
                ],
            ),
        ),
        _trends_case(
            name="trends_avg_session_duration",
            prompt="what is our average session duration?",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="$all_events",
                        math="avg",
                        math_property="$session_duration",
                        properties=None,
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_pageviews_unique_sessions",
            prompt="how many $pageviews with unique sessions did we have?",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="$pageview",
                        math="unique_session",
                        properties=None,
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_pageview_this_january",
            prompt="How often do users view the website in this January?",
            query=AssistantTrendsQuery(
                dateRange={
                    "date_from": f"{datetime.now().year}-01-01",
                    "date_to": f"{datetime.now().year}-01-31",
                },
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="$pageview",
                        math="total",
                        properties=None,
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_paid_bill_january_over_20usd",
            prompt="How many paid bill events have occurred with amount more than 20 usd in this January?",
            query=AssistantTrendsQuery(
                dateRange={
                    "date_from": f"{datetime.now().year}-01-01",
                    "date_to": f"{datetime.now().year}-01-31",
                },
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="ActionsLineGraph",
                    showLegend=True,
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event="paid_bill",
                        math="total",
                        properties=[
                            {
                                "key": "amount_usd",
                                "value": 20,
                                "operator": "gt",
                                "type": "event",
                            },
                        ],
                    )
                ],
            ),
        ),
        _trends_case(
            name="trends_hedgebox_mac_os_pct",
            prompt="on hedgebox.net, what is the % of mac os x users",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "-30d", "date_to": None},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(
                    display="BoldNumber", showLegend=True, formulaNodes=[TrendsFormulaNode(formula="B/A * 100")]
                ),
                series=[
                    AssistantTrendsEventsNode(
                        event=None,
                        math="dau",
                        properties=[
                            {
                                "key": "$host",
                                "value": "hedgebox.net",
                                "operator": "icontains",
                                "type": "event",
                            },
                        ],
                    ),
                    AssistantTrendsEventsNode(
                        event=None,
                        math="dau",
                        properties=[
                            {
                                "key": "$host",
                                "value": "hedgebox.net",
                                "operator": "icontains",
                                "type": "event",
                            },
                            {
                                "key": "$os",
                                "value": "Mac OS X",
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    ),
                ],
            ),
        ),
        # Specific, uppercase event to use, which doesn't exist in the actual data (but the user quotes it specifically anyway)
        _trends_case(
            name="trends_onboarding_completed_january_2025",
            prompt="How many 'Onboarding Completed' events have we had in January 2025?",
            query=AssistantTrendsQuery(
                dateRange={"date_from": "2025-01-01", "date_to": "2025-01-31"},
                filterTestAccounts=True,
                interval="day",
                trendsFilter=AssistantTrendsFilter(display="ActionsLineGraph"),
                series=[
                    AssistantTrendsEventsNode(
                        event="Onboarding Completed",
                        math="total",
                        properties=None,
                    )
                ],
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-trends",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            LastToolCallNot(forbidden="execute-sql", name="last_call_not_execute_sql"),
            SkillLoaded("providing-insights", name="providing_insights_skill_loaded"),
            TrendsSchemaAlignment(),
            TrendsTimeRangeRelevancy(),
        ],
        ctx=ctx,
    )
