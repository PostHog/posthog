"""Eval: does the agent assemble a correctly shaped metric on the FIRST experiment-update call?

Grades whether the proactive schema guidance in the
``configuring-experiment-analytics`` skill prevents the "fail, read pydantic
error, retry" pattern from being the only path to success. Two cases:

* ``ratio_metric_uses_math_sum`` — a revenue-per-pageview ratio must aggregate
  with ``math: "sum"`` + ``math_property: "revenue"``, not an ``is_set`` filter.
* ``retention_metric_first_try`` — a 7-day retention metric must carry
  ``retention_window_start`` and ``start_handling`` up front.

``FirstUpdateMetricShape`` grades the first ``experiment-update`` call only, so
recovering on a later call does not flip the score.
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.posthog_ai.evals.experiments.scorers import (
    FirstUpdateMetricShape,
    validate_ratio_revenue_metric,
    validate_retention_metric,
)
from products.posthog_ai.evals.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment


async def eval_metric_schema_discovery(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="ratio_metric_uses_math_sum",
            prompt=(
                f"Add a ratio metric to '{ROLLOUT_EXPERIMENT_NAME}' for total revenue (the `revenue` "
                "property on `purchase_completed`) per `$pageview`. These events aren't instrumented "
                "yet — that's intended, so allow unknown events without asking."
            ),
            setup=seed_running_experiment,
            expected={"first_update_metric_shape": validate_ratio_revenue_metric},
        ),
        SandboxedEvalCase(
            name="retention_metric_first_try",
            prompt=(
                f"Add a 7-day retention metric to '{ROLLOUT_EXPERIMENT_NAME}', `$pageview` → "
                "`uploaded_file`. These events aren't instrumented yet — that's intended, so allow "
                "unknown events without asking."
            ),
            setup=seed_running_experiment,
            expected={"first_update_metric_shape": validate_retention_metric},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-experiments-metric-schema-discovery-cli",
        cases=cases,
        scorers=[
            RequiredToolCall(required={"experiment-update"}, name="called_experiment_update"),
            FirstUpdateMetricShape(),
        ],
        ctx=ctx,
    )
