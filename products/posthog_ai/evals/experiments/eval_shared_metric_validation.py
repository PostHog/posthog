"""Eval: agent reads a shared metric and validates it against user-stated acceptance criteria.

Two cases — one where criteria match the seeded metric, one where they
don't. Agent must (1) load the metric via the saved-metrics MCP tools
and (2) reach the correct verdict citing grounded discrepancies.
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.posthog_ai.evals.experiments.scorers import SharedMetricValidationVerdict
from products.posthog_ai.evals.experiments.seeders import SHARED_METRIC_NAME, seed_shared_metric_purchase_count


async def eval_shared_metric_validation(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        # Case 1: criteria match the seeded metric exactly. Agent should
        # affirm the match and cite the event and math.
        SandboxedEvalCase(
            name="shared_metric_matches_criteria",
            prompt=(
                f"I just defined a shared experiment metric called '{SHARED_METRIC_NAME}'. "
                "My acceptance criteria: it must count the number of `purchase_completed` "
                "events per user (a simple total count, no revenue summing). Please load "
                "the metric and tell me whether it matches my criteria. Be specific about "
                "which dimensions match or don't."
            ),
            setup=seed_shared_metric_purchase_count,
            expected={"shared_metric_validation_verdict": "match"},
        ),
        # Case 2: criteria explicitly assert a different event AND a different
        # math/aggregation than the seeded metric. Agent should reject the
        # match and name at least one specific discrepancy.
        SandboxedEvalCase(
            name="shared_metric_mismatch_criteria",
            prompt=(
                f"I just defined a shared experiment metric called '{SHARED_METRIC_NAME}'. "
                "My acceptance criteria: it must sum the `revenue` property from `$purchase` "
                "events per user (total revenue per user, not a count). Please load the "
                "metric and tell me whether it matches my criteria. Be specific about which "
                "dimensions match or don't."
            ),
            setup=seed_shared_metric_purchase_count,
            expected={"shared_metric_validation_verdict": "mismatch"},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-shared-metric-validation-cli",
        cases=cases,
        scorers=[
            # Agent must actually read the seeded metric — either via list
            # (to resolve by name) or retrieve (by ID). Hallucinating a
            # verdict without reading the metric should fail this scorer.
            RequiredToolCall(
                required={"experiment-saved-metrics-list", "experiment-saved-metrics-retrieve"},
                name="loaded_shared_metric",
            ),
            SharedMetricValidationVerdict(),
        ],
        ctx=ctx,
    )
