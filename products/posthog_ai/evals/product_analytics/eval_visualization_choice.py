"""Does the sandboxed agent pick the preferred chart type for a question?

Two preferences the tool descriptions steer toward: a single number over a period
gets the ``Metric`` display rather than ``BoldNumber``, and a question about how
conversion changes over time gets a funnel with ``funnelVizType: trends`` rather
than ``steps``. ``InsightShape`` checks the tool, display, and funnel viz of the
typed query the agent ran.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; hogli evals eval_visualization_choice --max-sandboxes 1"
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.product_analytics.scorers import INSIGHT_WRITE_TOOLS, InsightShape


def _case(name: str, prompt: str, **shape: Any) -> SandboxedEvalCase:
    return SandboxedEvalCase(name=name, prompt=prompt, expected={"insight_shape": shape})


async def eval_visualization_choice(ctx: EvalContext) -> None:
    cases = [
        _case(
            "metric_signups_last_30_days",
            "What's the total number of signups in the last 30 days?",
            tool="query-trends",
            display="Metric",
            events=["signed_up"],
        ),
        _case(
            "metric_uploads_last_24_hours",
            "How many files were uploaded in the last 24 hours?",
            tool="query-trends",
            display="Metric",
            events=["uploaded_file"],
        ),
        _case(
            "funnel_steps_signup_to_upload",
            "What's the conversion rate from signing up to uploading a first file?",
            tool="query-funnel",
            funnel_viz="steps",
            event_sequence=["signed_up", "uploaded_file"],
        ),
        _case(
            "funnel_over_time_signup_to_upload",
            "How has conversion from signing up to uploading a file changed week by week over the last 8 weeks?",
            tool="query-funnel",
            funnel_viz="trends",
            event_sequence=["signed_up", "uploaded_file"],
        ),
        _case(
            "funnel_over_time_upgrade_improving",
            "Is our conversion from signup to plan upgrade improving?",
            tool="query-funnel",
            funnel_viz="trends",
            event_sequence=["signed_up", "upgraded_plan"],
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-visualization-choice-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            InsightShape(),
        ],
        ctx=ctx,
    )
