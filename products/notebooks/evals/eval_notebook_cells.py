"""Eval cases for authoring notebook cells over MCP.

Both lanes a cell run can take are graded here, because they fail in different places:
a SQL cell rides the direct HogQL lane and never provisions anything, while a python
cell dispatches a Temporal workflow that provisions the notebook kernel sandbox.

To run one case:
    hogli evals eval_notebook_cells --eval sql_cell_report
"""

from __future__ import annotations

from products.notebooks.evals.scorers import CellRunsCompleted, NotebookCreated
from products.notebooks.evals.seeders import seed_case_team
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_notebook_cells(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            # Cheapest possible kernel-lane check: no query, no dataframe, no dependency
            # between cells. When this passes and the cases below fail, the sandbox is fine
            # and the agent's analysis is what broke.
            name="python_cell_arithmetic",
            prompt=("Create a notebook called 'Kernel smoke test'. Add a Python cell that prints the result of 1 + 2."),
            expected={
                "notebook_created": {},
                "cell_runs_completed": {"node_types": ["python"]},
            },
            setup=seed_case_team,
        ),
        SandboxedEvalCase(
            name="sql_cell_report",
            prompt=(
                "Create a notebook called 'Signup momentum'. Add a SQL cell that returns weekly counts "
                "of `signed_up` events over the last 8 weeks, and finish with a short markdown summary "
                "of what the numbers show."
            ),
            expected={
                "notebook_created": {},
                "cell_runs_completed": {"node_types": ["hogql"]},
            },
            setup=seed_case_team,
        ),
        SandboxedEvalCase(
            name="python_cell_from_dataframe",
            prompt=(
                "Create a notebook called 'Signup momentum'. Add a SQL cell that returns weekly counts "
                "of `signed_up` events over the last 8 weeks, then add a Python cell that reads that "
                "cell's dataframe and computes the week-over-week percentage change. Finish with a short "
                "markdown summary naming the week that grew the most."
            ),
            expected={
                "notebook_created": {},
                # Both lanes: the SQL cell proves the direct path, the python cell proves the
                # kernel sandbox was provisioned, ran the code, and reported back.
                "cell_runs_completed": {"node_types": ["hogql", "python"]},
            },
            setup=seed_case_team,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-notebook-cells-cli",
        cases=cases,
        scorers=[
            RequiredToolCall({"notebooks-add-cell"}),
            NotebookCreated(),
            CellRunsCompleted(),
        ],
        ctx=ctx,
    )
