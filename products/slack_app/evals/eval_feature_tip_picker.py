"""Which feature tip fits a message the person sent to PostHog in Slack?

A tip goes under an answer when one is due. With two or more candidate features,
`classify_feature_tip` asks Jev, a System One decision model, to pick the one that fits the
message, or `none`. A pick below `FEATURE_TIP_MIN_CONFIDENCE` falls back to the ranked order.

`no_forced_tip` is the number to watch: a tip that claims to fit a message it does not fit reads
as an ad. A missed match only costs the ranked tip, which is still a valid tip.

To run:
    hogli evals eval_feature_tip_picker
    hogli evals eval_feature_tip_picker --eval fix_checkout_error
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.backend.logic.feature_tips import picker
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG, SlackFeature
from products.slack_app.evals.scorers import FEATURE_TIP_KEY, FeatureTipMatch, NoForcedTip

SUITE_KIND = SuiteKind.ONE_SHOT

ALL_FEATURES = [feature.value for feature in SlackFeature]


def _case(name: str, prompt: str, expected: str, candidates: list[str] | None = None) -> BaseEvalCase:
    return BaseEvalCase(
        name=name,
        prompt=prompt,
        expected={FEATURE_TIP_KEY: {"feature": expected}},
        metadata={"candidates": candidates or ALL_FEATURES},
    )


MATCH_CASES = [
    _case("fix_checkout_error", "can you fix the TypeError on the checkout page?", "code_change_pr"),
    _case("add_tracking", "we don't track when people export a file, can you add an event for it?", "code_change_pr"),
    _case("weekly_signups", "what were our signups this week compared to last week?", "subscription"),
    _case("monday_numbers", "give me the weekly active users number, I need it for the Monday update", "subscription"),
    _case("linear_ticket", "look at the bug in our Linear ticket about broken uploads", "mcp_tool"),
    _case("notion_spec", "compare the funnel with what the onboarding spec in Notion says", "mcp_tool"),
    _case("follow_up", "and what about the same numbers for mobile?", "thread_followup"),
    _case(
        "one_customer_revenue", "how much revenue did we get from our biggest customer last quarter?", "direct_message"
    ),
]

NO_MATCH_CASES = [
    _case("plain_count", "how many people visited the pricing page yesterday?", "none", ["code_change_pr", "mcp_tool"]),
    _case("flag_state", "is the new-onboarding flag rolled out to everyone?", "none", ["mcp_tool", "direct_message"]),
    # The obvious feature is not a candidate, so the model must not pick a near one.
    _case(
        "bug_without_pr_candidate", "fix the null error in the signup form", "none", ["subscription", "direct_message"]
    ),
    _case("recurring_without_subscription", "send me signups every Monday", "none", ["code_change_pr", "mcp_tool"]),
]


async def eval_feature_tip_picker(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = picker.FEATURE_TIP_DECISION_MODEL
        candidates = [CATALOG[SlackFeature(value)] for value in (case.metadata or {}).get("candidates", ALL_FEATURES)]
        if task_ctx.demo_data is None:
            return {"decision_model": model, "feature": None, "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            verdict = await asyncio.to_thread(
                picker.classify_feature_tip,
                case.prompt,
                candidates,
                team_id=task_ctx.demo_data.master_team_id,
                distinct_id=None,
            )
        except Exception as error:
            return {"decision_model": model, "feature": None, "error": f"{type(error).__name__}: {error}"}
        # The same rule production applies: a pick below the threshold counts as no match.
        picked = (
            verdict.choice
            if verdict is not None and verdict.confidence >= picker.FEATURE_TIP_MIN_CONFIDENCE
            else picker.NO_FEATURE
        )
        return {
            "decision_model": model,
            "feature": picked,
            "verdict": {"choice": verdict.choice, "confidence": verdict.confidence} if verdict else None,
            "last_message": f"{model}: feature={picked}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-feature-tip-picker",
        cases=[*MATCH_CASES, *NO_MATCH_CASES],
        scorers=[FeatureTipMatch(), NoForcedTip()],
        task=task,
        ctx=ctx,
    )
