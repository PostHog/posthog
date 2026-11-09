from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext

from .first_report_scorers import GroundedCloseout, PlantedIssueRecall, ReportQuality, ScoutOutcome
from .first_report_seeders import seed_sparse_project, seed_upload_control, seed_upload_regression
from .offline_config import FIRST_REPORT_SUITE
from .scout_runner import run_first_report_scout


async def eval_first_report(ctx: EvalContext) -> None:
    if ctx.skill_delivery != "bundled":
        raise ValueError("Scout evals use the production bundled skill configuration")
    await SandboxedEval(
        offline_suite=FIRST_REPORT_SUITE,
        send_to_posthog=True,
        experiment_name="first-report-scout",
        cases=[
            SandboxedEvalCase(
                name="upload_regression",
                prompt="Run the production first-report scout.",
                setup=seed_upload_regression,
                expected={"scenario": "regression"},
            ),
            SandboxedEvalCase(
                name="upload_control",
                prompt="Run the production first-report scout.",
                setup=seed_upload_control,
                expected={"scenario": "control"},
            ),
            SandboxedEvalCase(
                name="sparse_project",
                prompt="Run the production first-report scout.",
                setup=seed_sparse_project,
                expected={"scenario": "sparse"},
                inherit_demo_data=False,
            ),
        ],
        scorers=[
            ScoutOutcome(),
            GroundedCloseout(),
            ReportQuality(),
            ReportQuality(deadline_seconds=300),
            PlantedIssueRecall(),
        ],
        case_runner=run_first_report_scout,
        ctx=ctx,
    )
