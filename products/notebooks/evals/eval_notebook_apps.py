from __future__ import annotations

from products.notebooks.evals.offline_config import offline_suite
from products.notebooks.evals.scorers import CellRunsCompleted, NotebookAppReady, NotebookCreated, NotebookRunCompleted
from products.notebooks.evals.seeders import seed_case_team
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_notebook_apps(ctx: EvalContext) -> None:
    await SandboxedEval(
        experiment_name="sandboxed-notebook-apps-cli",
        offline_suite=offline_suite(
            "notebooks/eval_notebook_apps::eval_notebook_apps",
            metrics=[
                "notebook_created",
                "cell_runs_completed",
                "notebook_run_completed",
                "notebook_app_ready",
                "app_saved",
                "widget_generation_requested",
                "widget_status_checked",
            ],
        ),
        cases=[
            SandboxedEvalCase(
                name="variable_driven_app_with_generated_widget",
                prompt=(
                    "Build a PostHog notebook app called 'Signup explorer'. Use our signed_up events. "
                    "Include a weeks control defaulting to 8, a weekly signup chart, a calculated total, "
                    "and a custom AI-generated widget showing progress toward a target of 1000 signups. "
                    "Make target another app control. The widget's title and progress must use the actual "
                    "selected target and calculated signup data, not hardcoded values. Use Python for "
                    "the progress calculation. I approve generating the widget with AI credits; I will "
                    "review and approve its generated preview separately. Verify that changing weeks to "
                    "4 changes the results, then restore 8 and run the whole notebook. Save the app draft "
                    "without publishing it. Finish with its link and any remaining approval step."
                ),
                expected={
                    "notebook_created": {},
                    "cell_runs_completed": {"node_types": ["hogql", "python"]},
                    "notebook_run_completed": {"variables": {"weeks": 8, "target": 1000}},
                    "notebook_app_ready": {"inputs": ["weeks", "target"]},
                },
                setup=seed_case_team,
            )
        ],
        scorers=[
            NotebookCreated(),
            CellRunsCompleted(),
            NotebookRunCompleted(),
            NotebookAppReady(),
            RequiredToolCall({"notebooks-app-update"}, name="app_saved"),
            RequiredToolCall({"notebooks-widget-generate"}, name="widget_generation_requested"),
            RequiredToolCall({"notebooks-widget-status"}, name="widget_status_checked"),
        ],
        ctx=ctx,
    )
