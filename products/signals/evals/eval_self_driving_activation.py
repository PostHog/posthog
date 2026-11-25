"""Does the coding agent pass on the Self-driving activation notice while it does ordinary error tracking work?

The real agent runs in a sandbox against the real MCP server. The server attaches the notice to the first successful error tracking list or detail call of a conversation, when the team has not started Self-driving setup. The harness turns the rule's flag on, and the rule accepts the harness's `eval` consumer in development. Every case sets that consumer itself, because with bundled skills the harness otherwise connects as `posthog_ai`, the in-app assistant, which never gets guidance notices. Every case seeds the same error tracking issues. The control case also marks Self-driving setup as complete, so the rule stays silent and a Self-driving mention there is not caused by the notice.

To run:
    hogli evals signals/eval_self_driving_activation --agent-model claude-opus-5-5 --trials 5 --provider modal
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade.agents import EVAL_INTERACTION_ORIGIN

from .self_driving_activation_scorers import (
    ActivationLinkPresent,
    ActivationNoticeDelivered,
    AnsweredQuestionFirst,
    NoUnpromptedSuggestion,
    SelfDrivingMentioned,
    SelfDrivingSuggested,
)
from .self_driving_activation_seeders import seed_errors_before_self_driving, seed_errors_with_self_driving_active

TOP_ERRORS_PROMPT = "What are the top errors in our app this week?"

CASES = [
    SandboxedEvalCase(
        name="top_errors_this_week",
        prompt=TOP_ERRORS_PROMPT,
        setup=seed_errors_before_self_driving,
        interaction_origin=EVAL_INTERACTION_ORIGIN,
    ),
    SandboxedEvalCase(
        name="team_invite_error_likely_cause",
        prompt=(
            "People say sending a team invite from the settings page fails with an error. "
            "Can you dig into that error and tell me what's most likely causing it?"
        ),
        setup=seed_errors_before_self_driving,
        interaction_origin=EVAL_INTERACTION_ORIGIN,
    ),
    SandboxedEvalCase(
        name="new_or_regressing_errors",
        prompt="Which errors are new or getting worse this week, and what should we look at first?",
        setup=seed_errors_before_self_driving,
        interaction_origin=EVAL_INTERACTION_ORIGIN,
    ),
    SandboxedEvalCase(
        name="top_errors_this_week_self_driving_active",
        prompt=TOP_ERRORS_PROMPT,
        setup=seed_errors_with_self_driving_active,
        expected={"self_driving_active": True},
        interaction_origin=EVAL_INTERACTION_ORIGIN,
    ),
]


async def eval_self_driving_activation(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-self-driving-activation-cli",
        cases=CASES,
        scorers=[
            ActivationNoticeDelivered(),
            SelfDrivingMentioned(),
            SelfDrivingSuggested(),
            ActivationLinkPresent(),
            AnsweredQuestionFirst(),
            NoUnpromptedSuggestion(),
        ],
        ctx=ctx,
        send_to_posthog=False,
    )
