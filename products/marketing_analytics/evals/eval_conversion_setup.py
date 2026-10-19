from __future__ import annotations

from products.actions.backend.models.action import Action
from products.marketing_analytics.evals.scorers import (
    PREVIEW_TOOL,
    ConversionPreviewDefinition,
    ConversionRecommendationEvidence,
    NoConversionSetupWrites,
)
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.posthog_ai.evals.cli_mcp.skill_distribution_scorers import (
    ExpectedSkillLoaded,
    SkillLoadedBeforeTool,
    skill_distribution_expectations,
)
from products.tasks.backend.facade.agents import EVAL_INTERACTION_ORIGIN, CustomPromptSandboxContext

SKILL = "setting-up-marketing-conversions"
ENGAGEMENT_ACTION = "Interacted with file"


def seed_existing_action(context: CustomPromptSandboxContext) -> dict[str, int]:
    action = Action.objects.get(team_id=context.team_id, name=ENGAGEMENT_ACTION, deleted=False)
    return {"action_id": action.id}


async def eval_conversion_setup(ctx: EvalContext) -> None:
    skill_expectations = skill_distribution_expectations(SKILL, [PREVIEW_TOOL], ctx.skill_delivery)
    await SandboxedPrivateEval(
        experiment_name="sandboxed-marketing-conversion-setup-cli",
        cases=[
            SandboxedEvalCase(
                name="paid_revenue_recommendation",
                interaction_origin=EVAL_INTERACTION_ORIGIN,
                prompt=(
                    "Help me set up a paid subscription revenue conversion goal in Marketing analytics. "
                    "Our monthly bill amounts are recorded in US dollars, not cents. We want every bill's "
                    "collected amount, including repeat bills, not a count of first-time customers. "
                    "Inspect the existing setup and available events, recommend a goal, and preview it for "
                    "the last 14 days excluding the project's configured test accounts. Explain the measured "
                    "results and anything the preview does not validate. This is a read-only review: do not "
                    "save or modify goals, actions, views, or project settings."
                ),
                expected={
                    **skill_expectations,
                    "conversion_preview_definition": {
                        "kind": "EventsNode",
                        "event": "paid_bill",
                        "math": "sum",
                        "math_property": "amount_usd",
                        "math_property_revenue_currency": {"static": "USD"},
                        "counts_as_revenue": True,
                        "counts_as_customer": False,
                    },
                    "conversion_recommendation_evidence": {
                        "criterion": (
                            "Recommend paid_bill summed by amount_usd in USD as paid revenue. Explain that "
                            "recurring bill payments do not establish first-time customers. Do not promote "
                            "file sizes, logins, or plan changes as collected revenue."
                        )
                    },
                },
            ),
            SandboxedEvalCase(
                name="existing_action_recommendation",
                interaction_origin=EVAL_INTERACTION_ORIGIN,
                setup=seed_existing_action,
                prompt=(
                    f"In Marketing analytics, review our existing '{ENGAGEMENT_ACTION}' action as an engagement "
                    "conversion goal. Count every matching event, including repeat interactions, and keep all "
                    "of the action's matching steps. This is an engagement goal, not revenue or a definition "
                    "of a paying customer. Inspect the current setup and preview the proposed goal for the "
                    "last 14 days excluding the project's configured test accounts. Show the measured results "
                    "and limitations. Do not save or modify goals, actions, views, or project settings."
                ),
                expected={
                    **skill_expectations,
                    "conversion_preview_definition": {
                        "kind": "ActionsNode",
                        "math": "total",
                        "counts_as_revenue": False,
                        "counts_as_customer": False,
                    },
                    "conversion_recommendation_evidence": {
                        "criterion": (
                            "Recommend the existing Interacted with file action as a count-based engagement "
                            "goal, preserving its ID and matching steps. Do not present the count as money "
                            "or new paying customers. A null preview value is unavailable, not zero revenue."
                        )
                    },
                },
            ),
        ],
        scorers=[
            ExpectedSkillLoaded(),
            SkillLoadedBeforeTool(),
            RequiredToolCall(["marketing-analytics-setup-plan"], name="read_marketing_setup"),
            RequiredToolCall(["marketing-analytics-conversion-goals"], name="read_existing_goals"),
            ConversionPreviewDefinition(),
            NoConversionSetupWrites(),
            ConversionRecommendationEvidence(),
        ],
        ctx=ctx,
    )
