"""Eval: guided experiment creation through the MCP, from the Roast #2 session.

A user asks the agent to set up a homepage experiment that improves activation. Two cases:

* ``newcomer``: the user says they are new to experiments and asks for guidance on best practices.
  The project gets about 10 visitors a month, and its only experiment is an A/A test the same user
  launched months ago and never ended (``seed_newcomer_project``, on an empty project).
* ``existing_user``: the same request without the newcomer line, on Hedgebox, which has healthy
  traffic and several experiments this user ran to the end (``seed_existing_user_project``).

Each case runs two turns. The skill asks about bucketing before it creates the experiment, and the
sandbox has no one to answer the question tool, so the agent server cancels the call and the agent
restates the question at the end of turn 1. Turn 2 answers it: go with the recommendations and create
the draft. Scorers grade the report the agent writes after creating the draft (see
``guided_creation_scorers``), and the "before the first question" judge grades turn 1 up to the draft.

The scorers set a baseline now and should pass as the Roast #2 PRs land. ``reminder_linked_to_experiment``
stays skipped until a case answers the closing question, for example with a third turn that accepts the
reminder.

``eval_inline_ui_guided_creation`` runs the same cases as PostHog Code (``interaction_origin="desktop"``).
The MCP then treats the client as an inline UI app host and shapes tool results the way it does for
Claude Code (``isInlineUiAppHost`` in ``services/mcp/src/tools/exec.ts``): ``experiment-create`` returns
its payload in ``structuredContent`` with a note not to repeat it. The harness can't send Claude Code's
own client header, so this is the closest profile. It needs ``--skill-delivery bundled``, because the
MCP doesn't serve skills through ``learn`` to PostHog Code.

To run:
    hogli evals experiments/eval_guided_creation::eval_guided_creation
    hogli evals experiments/eval_guided_creation::eval_inline_ui_guided_creation
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall, RequiredToolCall
from products.posthog_ai.evals.experiments.guided_creation_scorers import (
    ClosingQuestionWithOptions,
    CodeChangesSection,
    ExecuteSqlCallsBeforeCreate,
    ExperimentUrlInReport,
    FlagUrlInReport,
    LowTrafficNote,
    NewcomerPrimerUpFront,
    NextExperimentSuggestion,
    NoUnavailableToolMention,
    PlacesLinked,
    ReminderLinkedToExperiment,
    RuntimeWithTraffic,
)
from products.posthog_ai.evals.experiments.seeders import seed_existing_user_project, seed_newcomer_project
from products.posthog_ai.evals.offline_config import offline_suite

# See harness/discovery.py: scales the per-case timeout for every suite in this module.
MULTI_TURN_CASES = True

_REQUEST = (
    "I'd like to run an experiment on the homepage to improve activation. Keep it simple and don't spend "
    "much time on the code. Set up the experiment in PostHog."
)
NEWCOMER_PROMPT = f"{_REQUEST} I'm a noob when it comes to experimentation, so I need guidance on best practices."
EXISTING_USER_PROMPT = _REQUEST
# Scoped to the setup questions, so a closing question that recommends launching isn't accepted by accident.
SETUP_ANSWER = "For your setup questions, go with what you recommend, and create the draft."

_NEWCOMER_ONLY_CHECKS = ("newcomer_primer_up_front", "low_traffic_note")


def _cases(*, interaction_origin: str | None = None) -> list[SandboxedEvalCase]:
    return [
        SandboxedEvalCase(
            name="newcomer",
            prompt=NEWCOMER_PROMPT,
            followups=[SETUP_ANSWER],
            setup=seed_newcomer_project,
            inherit_demo_data=False,
            interaction_origin=interaction_origin,
            expected=dict.fromkeys(_NEWCOMER_ONLY_CHECKS, True),
        ),
        SandboxedEvalCase(
            name="existing_user",
            prompt=EXISTING_USER_PROMPT,
            followups=[SETUP_ANSWER],
            setup=seed_existing_user_project,
            interaction_origin=interaction_origin,
            expected=dict.fromkeys(_NEWCOMER_ONLY_CHECKS, False),
        ),
    ]


def _scorers() -> list:
    return [
        ExperimentUrlInReport(),
        FlagUrlInReport(),
        RequiredToolCall(required={"experiment-create"}, name="experiment_created_successfully"),
        NoToolCall(forbidden=["experiment-launch"], name="no_unprompted_launch"),
        ExecuteSqlCallsBeforeCreate(),
        NoUnavailableToolMention(),
        NewcomerPrimerUpFront(),
        CodeChangesSection(),
        NextExperimentSuggestion(),
        ClosingQuestionWithOptions(),
        RuntimeWithTraffic(),
        LowTrafficNote(),
        PlacesLinked(),
        ReminderLinkedToExperiment(),
    ]


async def _run(ctx: EvalContext, *, function: str, experiment_name: str, interaction_origin: str | None) -> None:
    scorers = _scorers()
    await SandboxedEval(
        experiment_name=experiment_name,
        send_to_posthog=True,
        offline_suite=offline_suite(
            f"experiments/eval_guided_creation::{function}",
            metrics=[scorer._name() for scorer in scorers],
        ),
        cases=_cases(interaction_origin=interaction_origin),
        scorers=scorers,
        ctx=ctx,
    )


async def eval_guided_creation(ctx: EvalContext) -> None:
    await _run(
        ctx,
        function="eval_guided_creation",
        experiment_name="sandboxed-experiments-guided-creation-cli",
        interaction_origin=None,
    )


async def eval_inline_ui_guided_creation(ctx: EvalContext) -> None:
    if ctx.skill_delivery != "bundled":
        raise ValueError("The inline UI profile needs --skill-delivery bundled: the MCP serves PostHog Code no skills")
    await _run(
        ctx,
        function="eval_inline_ui_guided_creation",
        experiment_name="sandboxed-experiments-guided-creation-inline-ui-cli",
        interaction_origin="desktop",
    )
