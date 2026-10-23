"""Which feature tip fits a message the person sent to PostHog in Slack?

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
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.evals.offline_config import offline_suite
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

# A reader rarely qualifies for every feature, so these cases pass the short lists a real reader gets.
NEW_FEATURE_CASES = [
    _case(
        "screenshot_of_bug",
        "the chart on my screen shows a gap on Tuesday, why?",
        "file_attachments",
        ["file_attachments", "subscription", "model_in_mention"],
    ),
    _case(
        "export_rows",
        "give me a list of all users who churned last month with their plan",
        "file_outputs",
        ["file_outputs", "thread_followup", "answer_rating"],
    ),
    _case(
        "error_spike_watch",
        "did we get any new errors after yesterday's deploy?",
        "inbox_channel",
        ["inbox_channel", "subscription", "app_home_tasks"],
    ),
    _case(
        "named_project",
        "for the mobile app, how many people opened the settings screen?",
        "project_in_mention",
        ["project_in_mention", "file_outputs", "answer_rating"],
    ),
    _case(
        "deep_investigation",
        "do a deep investigation into why retention dropped for the March cohort, take your time",
        "model_in_mention",
        ["model_in_mention", "insight_unfurl", "reply_suggestions"],
    ),
    _case(
        "earlier_task_status",
        "is the pull request you started this morning done yet?",
        "app_home_tasks",
        ["app_home_tasks", "file_attachments", "insight_unfurl"],
    ),
    _case(
        "share_a_chart",
        "I want to share the signup trend chart with the team here",
        "insight_unfurl",
        ["insight_unfurl", "direct_message", "answer_rating"],
    ),
    _case(
        "wrong_answer",
        "that number you gave me before was wrong, it should be much higher",
        "answer_rating",
        ["answer_rating", "file_outputs", "app_home_project"],
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
    # Near misses: the message mentions an app or an error but names no project and asks for no code change.
    _case(
        "app_without_project_name",
        "how many people opened the app yesterday?",
        "none",
        ["project_in_mention", "file_outputs"],
    ),
    _case(
        "error_count_without_fix",
        "how many users hit the TypeError on checkout this week?",
        "none",
        ["code_change_pr", "direct_message"],
    ),
]


async def eval_feature_tip_picker(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = picker.FEATURE_TIP_DECISION_MODEL
        candidates = [CATALOG[SlackFeature(value)] for value in (case.metadata or {}).get("candidates", ALL_FEATURES)]
        if task_ctx.demo_data is None:
            return {"decision_model": model, "feature": None, "error": "No demo data team to bill the call to"}
        try:
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
        offline_suite=offline_suite(
            "slack_app/eval_feature_tip_picker::eval_feature_tip_picker",
            metrics=[FEATURE_TIP_KEY, "no_forced_tip"],
            suite_kind=SUITE_KIND,
        ),
        cases=[*MATCH_CASES, *NEW_FEATURE_CASES, *NO_MATCH_CASES],
        scorers=[FeatureTipMatch(), NoForcedTip()],
        task=task,
        ctx=ctx,
    )
