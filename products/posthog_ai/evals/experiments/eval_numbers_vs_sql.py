"""Eval: agent handles PostHog-vs-SQL divergence in three shapes — scope mismatch, anti-routing and population mismatch.

Carrier scenarios for diagnostic group D from
``products/experiments/skills/diagnosing-experiment-health/SKILL.md``.

Three cases:

1. ``posthog_count_below_raw_sql`` — the user's hand-written SQL counts more
   events than PostHog's experiment view. The skill lists the canonical
   reasons (exposure scope, ``$multiple`` exclusion, test-account filter,
   date range) — agent should name at least one without treating SQL as
   ground truth.

2. ``exposures_vastly_exceed_metric`` — exposures sit at ~11k but the
   primary metric only counts ~110 events (a ~100× gap). Presents as a
   group-D scope mismatch but the root cause is identity / bucketing
   (group A — A3 fragmentation, A4 bootstrap × ``/flags``, or A6/A8
   identifier migration). The skill's dispatch table for this symptom
   explicitly says "route here before D" — this case tests whether the
   agent obeys that routing rule under surface pressure (it looks like a
   D problem) rather than just reciting it. Uses the inline-evidence
   pattern from ``srm_with_identity_fragmentation``: the prompt carries the
   bucketing signatures (`$multiple` share, distinct_id/person ratio) so
   the agent has the diagnostic evidence without needing seeded state to
   match.

3. ``insight_counts_narrower_population`` (D12) — the experiment reads flat
   while the team's own funnel insight, filtered to first-time visitors,
   shows a drop. The flag is evaluated for every visitor. The user offers
   the wrong conclusion ("the exposure settings are defaults, so the setup
   is fine"). The agent must compare the two populations and must not
   approve the setup from its defaults.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_numbers_vs_sql"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.experiments.scorers import CitesDiagnosticGroup
from products.posthog_ai.evals.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment


async def eval_numbers_vs_sql(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="posthog_count_below_raw_sql",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' shows about 500 users in the metric on the "
                "experiment page, but when I run my own SQL (`SELECT count(DISTINCT person_id) FROM "
                "events WHERE event = '$pageview' AND timestamp >= <start_date>`) I get 1000. PostHog "
                "seems to be missing half my users. Which number is right and why don't they match?"
            ),
            setup=seed_running_experiment,
            expected={
                # Broadened from "must be the primary focus" to "must be named somewhere in the
                # response": the agent's correct enumeration behavior (anti-bundle rule) means it
                # may surface auxiliary findings alongside the D-group diagnostic — e.g. if the
                # seeded project shows the flag isn't being called at all, the agent will (rightly)
                # surface that as a B-group finding. The skill's anti-bundle rule explicitly wants
                # multiple findings surfaced; this scorer should not penalize that.
                "diagnosis_group": (
                    "The agent names AT LEAST ONE of the scope filters that the PostHog experiment "
                    "view applies but raw SQL does not replicate — any of: (a) the test-account "
                    "filter (excluded by default), (b) the $multiple variant exclusion, (c) the "
                    "exposure-event scope (the experiment counts users who fired "
                    "$feature_flag_called, not arbitrary pageview users), or (d) the experiment's "
                    "date range. The agent must also frame the gap as 'PostHog and raw SQL measure "
                    "different populations' — i.e. PostHog's number is not wrong, the SQL is "
                    "missing scope filters. Surfacing the scope-filter mechanism ALONGSIDE other "
                    "findings (e.g. that the flag may not actually be called) qualifies; the "
                    "scope-filter explanation does not need to be the response's primary focus, "
                    "only present and substantively named."
                ),
            },
        ),
        SandboxedEvalCase(
            # Anti-routing test. Symptom looks like a D problem ("numbers don't match") but
            # the magnitude (two orders of magnitude gap between exposures and the metric)
            # is the signature of identity / bucketing failure, not scope reconciliation.
            # The skill's dispatch table for this exact shape says "route here before D" —
            # this case verifies the agent obeys the dispatch rule under the temptation of
            # the surface symptom.
            #
            # Inline-evidence pattern: the prompt itself carries the bucketing signatures
            # ($multiple share, distinct_id/person ratio) so the agent has everything needed
            # to route to A without verifying against project state.
            name="exposures_vastly_exceed_metric",
            prompt=(
                f"On my experiment '{ROLLOUT_EXPERIMENT_NAME}' I'm seeing something that looks "
                "like the numbers don't line up. Three observations:\n\n"
                "1. Exposures tab says about 11,000 users were exposed.\n\n"
                "2. The primary metric only counts about 110 events total — a 100× gap.\n\n"
                "3. The exposure breakdown on the experiment shows about 8% of people under "
                "`$multiple`, and in the raw exposure events the ratio of distinct distinct_ids "
                "per person_id is about 2× higher than I'd expect — many people seem to have "
                "multiple distinct IDs attached.\n\n"
                "The metric event scoping looks correct in the experiment page configuration. "
                "Where should I look first?"
            ),
            setup=seed_running_experiment,
            expected={
                # The skill's dispatch table maps "metric count is much smaller than exposures
                # (10× / 100× gap)" to group A first, not group D. With $multiple share and
                # distinct_id/person ratio both elevated in the prompt, the agent has decisive
                # inline evidence pointing at bucketing — there is no defensible reason to lead
                # with D scope filters.
                "diagnosis_group": (
                    "The agent identifies this is a bucketing / identity-resolution problem "
                    "(group A — A3 identity fragmentation, A4 bootstrap × /flags mismatch, or "
                    "A6/A8 identifier strategy change), NOT primarily a SQL scope mismatch "
                    "(group D). The inline evidence pins this: the elevated $multiple share "
                    "(~8%) plus the >1 distinct_ids/person ratio (~2×) are direct signatures of "
                    "identity fragmentation. The agent's response must lead with the identity / "
                    "bucketing route. An answer that leads with D scope filters (test-account "
                    "filter, $multiple exclusion as a scope filter, date range, conversion "
                    "window, etc.) without recognizing that the inline-reported $multiple and "
                    "distinct_id signals indicate a real bucketing problem fails — that is the "
                    "exact 'route here before D' miss the dispatch rule is designed to prevent."
                ),
            },
        ),
        SandboxedEvalCase(
            # D12: the user offers the wrong conclusion that default exposure settings make the setup sound.
            name="insight_counts_narrower_population",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' changes our signup page. The experiment "
                "says the test variant is flat on signups, but our own signup funnel insight, which "
                "only counts first-time visitors, shows a clear drop since launch. The flag is "
                "evaluated for everyone who opens the page, including logged-in customers. I left "
                "the exposure settings on their defaults, so the experiment setup itself should be "
                "fine, right?"
            ),
            setup=seed_running_experiment,
            expected={
                "diagnosis_group": (
                    "The agent does NOT confirm that the setup is fine because the exposure "
                    "settings are defaults. It identifies that the experiment and the insight count "
                    "different populations: the experiment counts everyone who was exposed, "
                    "including existing customers the change is not aimed at, while the insight "
                    "counts only first-time visitors, so the effect on new visitors is diluted in "
                    "the experiment's number. It recommends comparing the insight's filters with "
                    "the experiment's exposure criteria and release conditions and narrowing the "
                    "experiment to the people the decision is about, and notes that doing so on a "
                    "running experiment is a mid-run change. This is the D12 diagnostic."
                ),
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-diagnose-numbers-vs-sql-cli",
        cases=cases,
        scorers=[
            CitesDiagnosticGroup(),
        ],
        ctx=ctx,
    )
