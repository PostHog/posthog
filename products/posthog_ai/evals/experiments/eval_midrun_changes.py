"""Eval: agent handles mid-run / lifecycle scenarios across three carrier shapes.

Carrier scenarios for diagnostic group E from
``products/experiments/skills/diagnosing-experiment-health/SKILL.md``.

Three cases:

1. ``ship_variant_flag_flip_on_stopped_experiment`` (E7 — post-hoc) — the
   seeded experiment is *stopped* and its feature flag has been rewritten by
   ``experiment-ship-variant``; multivariate is now 0/100, and the verbatim
   E7 signature ("Added automatically when the experiment was ended to keep
   only one variant."), on the catch-all release condition that an "all
   users" ship prepends, sits in the activity log. Tests two behaviors: the
   agent names the ship-variant flip as the cause AND does not push reversal
   on a stopped experiment (Step 4 state-aware rule).

2. ``ship_variant_under_uncertainty`` (C10 / E7 — pre-ship guidance) — a
   *running* experiment, primary metric up but a secondary / guardrail metric
   trending negative. The user asks whether to ship the test variant. The
   correct behavior is to advise AGAINST a confident ship — flagging the
   guardrail, recommending more data or holding to control, and warning
   about the ship-variant release-mode choice (PR #58828 introduced
   "experiment population" vs "all users" — uncertain ships should not pick
   "all users"). This case tests the agent's pre-ship judgment, which the
   existing E7 post-hoc case does not exercise.

3. ``pause_inside_the_run`` (E9 — an interruption can bias the result) — a
   five-day pause inside a two-week run, then a resume, with nothing else
   changed. The agent must say that metric events of the paused days still
   count toward the test variant although nobody received it, so the result
   is biased, and must not call the run unaffected.

The seeder writes a real ``ActivityLog`` row carrying the synthetic 50/50 →
0/100 diff (with the verbatim "Added automatically when the experiment was
ended to keep only one variant." signature in
``detail.changes[].after.groups[].description``) so that any
investigation path the agent picks — reading the live flag config,
inspecting the activity log, or reading the stored results — surfaces real
production-shaped state. Which path the agent takes is not graded; only the
final diagnosis and the no-edit recommendation are.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_midrun_changes"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.experiments.scorers import (
    AdvisesAgainstShipping,
    CitesDiagnosticGroup,
    DoesNotRecommendEdit,
)
from products.posthog_ai.evals.experiments.seeders import (
    ENDED_EXPERIMENT_NAME,
    ROLLOUT_EXPERIMENT_NAME,
    seed_ended_experiment_with_flag_flip,
    seed_paused_and_resumed_experiment,
    seed_running_experiment,
)


async def eval_midrun_changes(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="ship_variant_flag_flip_on_stopped_experiment",
            prompt=(
                # Neutral framing — no "unexpectedly", no "by accident", no hint of remorse.
                # The user is asking what happened, not asking to undo it. The state-aware
                # rule (Step 4) requires the agent to explain only, not offer reversal
                # mechanics unprompted.
                f"My experiment '{ENDED_EXPERIMENT_NAME}' has ended. The feature flag is now rolling "
                "out the test variant to 100% of users, but I had it set up as a 50/50 split. "
                "Why is the flag distribution different from what I configured?"
            ),
            setup=seed_ended_experiment_with_flag_flip,
            expected={
                "diagnosis_group": (
                    "The flag was rewritten when the experiment was ended via ship-variant — PostHog "
                    "rewrites the multivariate distribution to 0/100 in favour of the shipped variant "
                    "and, in the 'all users' mode, prepends a release condition with the description "
                    "'Added automatically when the experiment was ended to keep only one variant.'. "
                    "This is the documented behavior of ship-variant, not an error."
                ),
                "does_not_recommend_edit": True,
            },
        ),
        SandboxedEvalCase(
            # Pre-ship judgment under conflicting metrics. Tests C10's "default to control
            # on ambiguous ships" rule and E7's release-mode caution. The user explicitly
            # asks "should I ship?" — the correct answer is "not yet / not on this evidence",
            # not "ship the test variant because the primary is up".
            name="ship_variant_under_uncertainty",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' has been running 10 days. The primary "
                "metric (signup conversion) is up about 8% in the test variant with a chance-to-win "
                "around 94%. But my guardrail secondary metric (7-day retention) is down about 3% "
                "in the test variant. Should I ship the test variant? And if so, should I roll it "
                "out to all users or just keep it scoped to the experiment population?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group tests identification only: did the agent name the
                # ship-variant default risk, guardrail vs primary tension, and release-mode
                # choice? Behavioral grading ("must not greenlight a ship") lives in
                # advises_against_shipping. Splitting them mirrors eval_interpretation_traps.py
                # — content and behavior regress on different axes and should be measured
                # independently.
                "diagnosis_group": (
                    "The agent identifies at least one of these as the relevant diagnostic: "
                    "(a) the guardrail / secondary metric trending negative is something the "
                    "ship-variant flow does NOT check — the product reads no metric before a "
                    "ship, so the user has to weigh the guardrail, (b) the primary's "
                    "chance-to-win is in the noise band where early flips happen, so the "
                    "significance is not settled, (c) on ambiguous ships the safe default is "
                    "to keep control rather than ship the test variant. If "
                    "release mode is discussed, the agent should prefer 'experiment "
                    "population' (default) over 'all users' — uncertain ships should not "
                    "extend the blast radius past the experiment's existing population."
                ),
                "advises_against_shipping": True,
            },
        ),
        SandboxedEvalCase(
            # E9: the tempting wrong answer is "the split did not change, so the result is unaffected".
            name="pause_inside_the_run",
            prompt=(
                f"We paused my experiment '{ROLLOUT_EXPERIMENT_NAME}' for five days in the middle "
                "of a two-week run because of a release freeze, then resumed it. The split is "
                "unchanged and nothing else was edited. Can I read the results as if it had run "
                "the whole two weeks?"
            ),
            setup=seed_paused_and_resumed_experiment,
            expected={
                "diagnosis_group": (
                    "The agent explains that a pause turns the flag off, so people in the test "
                    "variant received the default (control) experience during the pause, while "
                    "their metric events from those days still count toward the test variant — "
                    "the analysis has no notion of the pause. The result is therefore biased (the "
                    "test arm is diluted toward control) in proportion to the pause. The agent "
                    "recommends stating the pause window with the result or, because five of "
                    "fourteen days is a large share, resetting and relaunching. This is the E9 "
                    "diagnostic. An answer that says the results are unaffected because the split "
                    "did not change fails."
                ),
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-diagnose-midrun-changes-cli",
        cases=cases,
        scorers=[
            CitesDiagnosticGroup(),
            DoesNotRecommendEdit(),
            AdvisesAgainstShipping(),
        ],
        ctx=ctx,
    )
