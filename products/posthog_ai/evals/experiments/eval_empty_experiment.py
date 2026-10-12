"""Eval: agent diagnoses empty / 0-exposure experiments across three carrier shapes.

Carrier scenarios for diagnostic group B from
``products/experiments/skills/diagnosing-experiment-health/SKILL.md``.

Three cases:

1. ``empty_experiment_inactive_flag`` (B10 / A5 — flag inactive) — the
   seeded experiment has ``start_date`` set so it *appears* running, but
   ``feature_flag.active=False`` — ``$feature_flag_called`` therefore cannot
   fire. Outcome-only pass: agent must name flag inactivity as the cause.

2. ``edited_exposure_criteria_still_zero`` (B4) — a high-frequency
   "edited exposure criteria, exposures still 0" shape. The user reports
   editing exposure criteria to a custom event, then states inline that the
   events ARE firing AND that they carry ``$feature_flag`` and
   ``$feature_flag_response`` but no ``$feature/<flag-key>``. The
   inline-evidence pattern (mirroring ``srm_with_identity_fragmentation`` in
   eval_bias_uneven_split) means the agent doesn't have to verify against the
   seeded state to identify the B4 diagnostic — the property gap *is* the
   evidence. The agent must name the missing ``$feature/<flag-key>`` property
   as the root cause.

3. ``test_account_filter_hides_internal_traffic`` (B7) — the user describes
   inline that ~50 internal teammates (all on a shared email domain) hit
   the experiment page, but exposures show only ~12 users captured. The
   internal team is silently being filtered by the project's
   ``test_account_filters`` (combined with the default
   ``exposure_criteria.filterTestAccounts=true``). Tests whether the agent
   identifies B7 from the symptom of "expected internal traffic missing
   from exposures" — a shape that the existing inactive_flag and
   property-gap cases don't exercise.

Tool-call path is not enforced — multiple valid investigation paths exist
(reading ``experiment-get``, reading the experiment's exposure data, or
running ``execute-sql`` on the raw exposure events).

To run:

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_empty_experiment"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.experiments.scorers import CitesDiagnosticGroup
from products.posthog_ai.evals.experiments.seeders import (
    INACTIVE_FLAG_EXPERIMENT_NAME,
    ROLLOUT_EXPERIMENT_NAME,
    seed_inactive_flag_experiment,
    seed_running_experiment,
)


async def eval_empty_experiment(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="empty_experiment_inactive_flag",
            prompt=(
                f"My experiment '{INACTIVE_FLAG_EXPERIMENT_NAME}' is showing 0 exposures and no data "
                "even though I think I started it days ago. Why is it empty?"
            ),
            setup=seed_inactive_flag_experiment,
            expected={
                "diagnosis_group": (
                    "The feature flag attached to the experiment is inactive (feature_flag.active=False), "
                    "so $feature_flag_called cannot fire — no users can ever be exposed. The experiment "
                    "is not actually live despite having a start_date set."
                ),
            },
        ),
        SandboxedEvalCase(
            # Inline-evidence pattern (mirrors srm_with_identity_fragmentation): the user
            # describes their custom event AND states inline which properties it carries.
            # The property gap ($feature_flag and $feature_flag_response set,
            # $feature/<flag-key> missing) IS the diagnostic evidence — the agent doesn't need project state to identify the
            # cause. The previous version of this case used surfaces_all_findings with
            # speculative auxiliary mechanisms; that bundling diluted the signal and the
            # agent's state-aware investigation routed around it. Single-mechanism
            # diagnosis_group is the honest grading shape for this prompt.
            name="edited_exposure_criteria_still_zero",
            prompt=(
                f"On my experiment '{ROLLOUT_EXPERIMENT_NAME}' I edited the exposure criteria after "
                "launch to use a custom event. The custom event IS firing regularly (~3000/day in "
                "raw event data) and each event carries `$feature_flag` set to my flag key and "
                "`$feature_flag_response` set to the variant — but no `$feature/<flag-key>` "
                "property. The experiment still shows 0 exposures after 7 days. What's the most "
                "likely cause?"
            ),
            setup=seed_running_experiment,
            expected={
                "diagnosis_group": (
                    "The custom exposure event is missing the property the experiment reads the "
                    "variant from. On a custom exposure event PostHog reads `$feature/<flag-key>`, "
                    "and it must hold one of the flag's variant keys (e.g. 'control', 'test'). "
                    "`$feature_flag` and `$feature_flag_response` are only read on the default "
                    "exposure event, so they do not help here. Without `$feature/<flag-key>` the "
                    "event is not an exposure at all, so the count stays at 0. This is the B4 "
                    "mechanism from group B. The agent's answer must center on the missing "
                    "`$feature/<flag-key>` property."
                ),
            },
        ),
        SandboxedEvalCase(
            # Inline-evidence pattern. The user describes a specific symptom shape — internal
            # teammates on a shared domain hitting the experiment page but not showing up in
            # exposures. The agent must identify that the project's test-account filter
            # (combined with the default exposure_criteria.filterTestAccounts=true) is
            # silently excluding them. The agent could also propose tactical verification
            # steps (toggle filterTestAccounts off, check the project's test_account_filters
            # rows); we only grade identification of the mechanism here.
            name="test_account_filter_hides_internal_traffic",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' has been running 5 days. We had about "
                "50 internal teammates (everyone on @hedgebox.com email) hit the page where the "
                "flag is read this week — I verified the page views landed in raw events. But "
                "the Exposures tab on the experiment only shows about 12 users captured, and "
                "none of my engineering colleagues appear in the per-user view. What's "
                "filtering them out?"
            ),
            setup=seed_running_experiment,
            expected={
                "diagnosis_group": (
                    "The agent identifies that the project's test-account filter is excluding "
                    "the internal teammates. PostHog's experiments apply "
                    "`exposure_criteria.filterTestAccounts` which defaults to `true` — when on, "
                    "events from users matching the project-level `test_account_filters` (e.g. "
                    "an internal email domain like `@hedgebox.com` or similar) are excluded "
                    "from the experiment, even though the raw events still land. This is the B7 "
                    "diagnostic. The agent's answer must name the test-account filter as the "
                    "cause; it should ideally also note that the filter is configurable per "
                    "experiment (filterTestAccounts) and the rule set is on the project."
                ),
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-diagnose-empty-cli",
        cases=cases,
        scorers=[
            CitesDiagnosticGroup(),
        ],
        ctx=ctx,
    )
