"""Skill-load eval for ``configuring-experiment-rollout``.

Asks the agent to change the variant split on a running experiment from
50/50 to 70/30 and grades whether the ``configuring-experiment-rollout``
skill auto-loaded before the agent took action. Single deterministic
scorer (``SkillLoaded``) — no LLM judge — so the signal is binary and
cheap to reproduce while iterating on the skill's description.

Maps to stress-test finding #7 (skills rarely auto-load), specifically
the variant-split rows (2.5, 5.3, 5.4, 5.5) in STEP_1_HARNESS.md. Uses
``SandboxedPrivateEval`` so it runs without a Braintrust API key —
local logs and PostHog ``$ai_trace`` events still emit.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_rollout_skill"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment
from products.posthog_ai.evals.retrieval.scorers import SkillLoaded

SKILL_NAME = "configuring-experiment-rollout"


async def eval_rollout_skill(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="rollout_change_split_70_30",
            prompt=(
                f"Change the variant split on the running experiment '{ROLLOUT_EXPERIMENT_NAME}' from 50/50 to 70/30."
            ),
            setup=seed_running_experiment,
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-rollout-cli",
        cases=cases,
        scorers=[
            SkillLoaded(skill_name=SKILL_NAME),
        ],
        ctx=ctx,
    )
