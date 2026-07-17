"""Eval: experiment-create must succeed when the user phrases variants
naturally (A vs B) without explicitly saying "control".

Background — the top experiment-create validation error in production
($exception telemetry, insight r43SObB1) is "Feature flag variants must
contain a control variant". 22 hits/week. Caused by the LLM mirroring
the user's natural language (A/B, old/new, original/redesign) and
emitting variant keys other than "control".

This eval guards three layers of the fix simultaneously, so a single
case covers a lot of ground:

1. Field-level schema description (``ExperimentVariant.key``) — the
   model should read the description and map A → "control" up front.
2. Server-side case-insensitive normalization — if the model emits
   "Control"/"CONTROL", the serializer rewrites it silently and the
   create still succeeds.
3. Self-correcting validation error — if the model emits "a"/"b",
   the new error message lists the keys received and tells it to
   rename the baseline; the model should retry and succeed.

Outcome scorer (``RequiredToolCall(experiment-create)``) is path-agnostic
on purpose — any of the three success paths above is fine. A regression
in any layer that prevents the agent from ever producing a successful
create call will flip this scorer to 0.0.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_create_control_variant"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_create_control_variant(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        # Single high-coverage case. The "A (existing) vs B (new)" framing
        # is the highest-yield trigger of the production "Feature flag
        # variants must contain a control variant" error: the user names
        # the variants and never says "control", so the agent has to map
        # the baseline (A) to the reserved key on its own.
        SandboxedEvalCase(
            name="create_with_natural_language_ab_variants",
            prompt=(
                "Create an experiment called 'pricing test' with feature flag key "
                "'pricing-test', comparing A (the existing pricing page) vs B (the new "
                "pricing page) with a 50/50 split. Don't ask follow-up questions — just "
                "create the draft."
            ),
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-create-control-cli",
        cases=cases,
        scorers=[
            # The single outcome scorer: did experiment-create return without error?
            # `RequiredToolCall` matches on `is_error=False`, so any of the three
            # paths in the docstring (clean call / silent normalization / retry
            # after better error message) counts as a pass.
            RequiredToolCall(
                required={"experiment-create"},
                name="experiment_created_successfully",
            ),
        ],
        ctx=ctx,
    )
