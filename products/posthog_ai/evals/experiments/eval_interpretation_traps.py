"""Eval: agent handles four interpretation-trap shapes from diagnostic group C.

Carrier scenarios for diagnostic group C from
``products/experiments/skills/diagnosing-experiment-health/SKILL.md``.

Four cases:

1. ``low_volume_30_16_split`` (C2 — small-sample variance) — the user supplies
   the numbers in the prompt (46 total exposures, 30/16 split) and asks
   whether this is a real signal AND whether to ship the control variant.
   The skill body lists this exact example as a wait-don't-act case.
   Graded on two dimensions:
   - ``CitesDiagnosticGroup`` — did the agent identify the small-sample
     mechanism?
   - ``AdvisesAgainstShipping`` — did the agent translate that diagnosis
     into "don't ship yet" guidance? This catches the failure mode where
     the agent identifies the issue but still greenlights a ship.

2. ``early_significance_notification`` (C9 — significance reached early) —
   user reports PostHog flagging significance at low sample / short runtime
   and asks whether to ship. Correct behavior is to treat the notification
   as a *prompt to review*, not an instruction to ship — wait for the
   pre-planned duration or for the signal to stabilise. Same two-scorer
   shape as case 1.

3. ``young_experiment_result_read`` (C1 — early reading) — one day into a
   three-week plan the user asks what drives an apparent lift and does not
   ask whether it is too early. The agent must state the experiment's age
   and its share of the planned sample before reading the result.

4. ``target_reached_no_significance`` (C12 — running-time label) — the
   duration estimate reads "Target reached" after four days on the default
   minimum detectable effect, nothing is significant, and the user reads the
   label as "finished". The agent must explain the label as a sample-size
   target and advise against closing the experiment on it.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_interpretation_traps"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.experiments.scorers import AdvisesAgainstShipping, CitesDiagnosticGroup
from products.posthog_ai.evals.experiments.seeders import (
    ROLLOUT_EXPERIMENT_NAME,
    seed_day_old_experiment,
    seed_running_experiment,
)


async def eval_interpretation_traps(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="low_volume_30_16_split",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' is configured as a 50/50 split, but I'm "
                "seeing a 30/16 split in actual exposures with only 46 total exposures so far. "
                "The control variant looks like it's winning. Is this a real signal or should I "
                "wait? Should I ship the control variant?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group tests identification of the small-sample mechanism.
                # advises_against_shipping tests behavioral translation into "don't ship".
                # Both are needed: the previous version of this case relied on diagnosis_group
                # alone, where the LLM judge's "must recommend waiting" criterion was bundled
                # into the diagnosis description — splitting them separates content from
                # behavior and makes regressions in either dimension visible independently.
                "diagnosis_group": (
                    "The agent identifies that 46 total exposures is too small a sample to draw "
                    "any conclusion — the observed 30/16 imbalance and the apparent winner are "
                    "both consistent with normal small-sample variance, not a real signal. The "
                    "skill's C2 (low-volume variance) diagnostic."
                ),
                "advises_against_shipping": True,
            },
        ),
        SandboxedEvalCase(
            # Inline-evidence pattern. The shape: PostHog flagged significance early, the user
            # reads "completed" as a green light and asks whether to ship. Correct behavior is
            # to treat the notification as a "prompt to review", not an instruction to ship —
            # wait for pre-planned duration, check guardrails, etc. The numbers (250/variant,
            # 36 hours) are far short of any planned duration and well inside the "early
            # flips" noise band.
            name="early_significance_notification",
            prompt=(
                f"PostHog just notified me that my experiment '{ROLLOUT_EXPERIMENT_NAME}' has "
                "reached significance — the test variant is winning on the primary metric "
                "(signup conversion) with a chance-to-win of 96%. We have about 250 exposures "
                "per variant and the experiment has been running for 36 hours. Should I ship "
                "the test variant now?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group: agent must identify that early significance with small
                # sample / short runtime is the C9 trap — verdict can revert as sample grows.
                # advises_against_shipping: agent must not greenlight a ship on this evidence.
                "diagnosis_group": (
                    "The agent identifies that a 'significance reached' notification at low "
                    "sample (~250/variant) and short runtime (36 hours) is not a green light to "
                    "ship — early significance can flip back to non-significant as more data "
                    "arrives. The agent should reference the planned sample or duration, "
                    "the noise band on early flips, or the C9 "
                    "diagnostic ('Significance reached notification is not a green light to "
                    "ship') in substance. An answer that takes the 96% chance-to-win at face "
                    "value without flagging the sample-size and runtime caveats fails."
                ),
                "advises_against_shipping": True,
            },
        ),
        SandboxedEvalCase(
            # C1: the user asks what drives the lift, not whether it is too early to read it.
            name="young_experiment_result_read",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' went live yesterday afternoon. The test "
                "variant already converts noticeably better than control on the primary metric, "
                "with roughly 120 exposures in each variant. We planned for about three weeks. "
                "Which part of the new design do you think is driving the lift?"
            ),
            setup=seed_day_old_experiment,
            expected={
                "diagnosis_group": (
                    "Before explaining the lift, the agent states that the experiment is about one "
                    "day old and holds only a small share of its planned sample (about 120 "
                    "exposures per variant against a three-week plan), so the difference is not a "
                    "readable result yet and can flip — the C1 early-reading / peeking diagnostic. "
                    "An answer that speculates about what drives the lift without that statement "
                    "fails. Naming sequential testing as the way to read results continuously is "
                    "fine but not required."
                ),
            },
        ),
        SandboxedEvalCase(
            # C12: the user reads the running-time label as the end of the experiment.
            name="target_reached_no_significance",
            prompt=(
                f"The duration estimate on my experiment '{ROLLOUT_EXPERIMENT_NAME}' switched to "
                "'Target reached' after four days, but none of the metrics is significant. I never "
                "changed the minimum detectable effect, so it is whatever the default is. Does that "
                "mean the test is finished and I should close it as inconclusive?"
            ),
            setup=seed_running_experiment,
            expected={
                "diagnosis_group": (
                    "The agent explains that 'Target reached' is the running-time estimate's sample "
                    "target for the configured minimum detectable effect — not a verdict and not "
                    "the end of the experiment. With a large default minimum detectable effect the "
                    "target is small, so reaching it only says that an effect of that size would "
                    "probably have shown. The agent advises against closing the experiment as "
                    "inconclusive on that label alone: set the minimum detectable effect to a "
                    "realistic effect and keep running. This is the C12 diagnostic. An answer that "
                    "confirms the experiment is finished fails."
                ),
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-diagnose-interpretation-cli",
        cases=cases,
        scorers=[
            CitesDiagnosticGroup(),
            AdvisesAgainstShipping(),
        ],
        ctx=ctx,
    )
