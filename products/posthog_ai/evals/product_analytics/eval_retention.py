"""Product analytics retention eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_retention.py`` — the CI version asserts
on the exact ``AssistantRetentionQuery`` Max produces, this version exercises
the same intents end-to-end through the sandboxed agent + PostHog MCP tools
and judges the retention query the agent ran via the ``query-retention`` MCP
tool.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_retention"
"""

from __future__ import annotations

from posthog.schema import AssistantRetentionEventsNode, AssistantRetentionFilter, AssistantRetentionQuery

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import LastToolCallNot, NoToolCall
from products.posthog_ai.evals.product_analytics.scorers import (
    INSIGHT_WRITE_TOOLS,
    RetentionSchemaAlignment,
    RetentionTimeRangeRelevancy,
)


def _retention_case(
    *,
    name: str,
    prompt: str,
    query: AssistantRetentionQuery,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "retention_query": query.model_dump(exclude_none=True),
        },
    )


async def eval_retention(ctx: EvalContext) -> None:
    cases = [
        _retention_case(
            name="retention_pageview_default",
            prompt="Show user retention",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11w", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="$pageview"),
                    targetEntity=AssistantRetentionEventsNode(id="$pageview"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_dashboard_monthly",
            prompt="Show monthly retention for users who sign up and then come back to view a dashboard",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11M", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Month",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="signed_up"),
                    targetEntity=AssistantRetentionEventsNode(id="viewed_dashboard"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_purchase_daily_chrome",
            prompt="daily retention for Chrome users who sign up and then make a purchase",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-14d", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Day",
                    totalIntervals=14,
                    returningEntity=AssistantRetentionEventsNode(
                        id="signed_up",
                        properties=[
                            {
                                "key": "$browser",
                                "value": "Chrome",
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                    ),
                    targetEntity=AssistantRetentionEventsNode(id="purchased"),
                ),
            ),
        ),
        _retention_case(
            name="retention_signup_to_purchase_weekly_3mo",
            prompt="weekly retention breakdown by browser for users who sign up and then make a purchase in the last 3 months",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-3m", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=12,
                    returningEntity=AssistantRetentionEventsNode(id="signed_up"),
                    targetEntity=AssistantRetentionEventsNode(id="purchased"),
                ),
            ),
        ),
        _retention_case(
            name="retention_pricing_to_upgrade",
            prompt="what's the retention for users who view the pricing page and then upgrade their plan?",
            query=AssistantRetentionQuery(
                dateRange={"date_from": "-11w", "date_to": None},
                filterTestAccounts=True,
                retentionFilter=AssistantRetentionFilter(
                    period="Week",
                    totalIntervals=11,
                    returningEntity=AssistantRetentionEventsNode(id="viewed_pricing_page"),
                    targetEntity=AssistantRetentionEventsNode(id="upgraded_plan"),
                ),
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-retention-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            LastToolCallNot(forbidden="execute-sql", name="last_call_not_execute_sql"),
            RetentionSchemaAlignment(),
            RetentionTimeRangeRelevancy(),
        ],
        ctx=ctx,
    )
