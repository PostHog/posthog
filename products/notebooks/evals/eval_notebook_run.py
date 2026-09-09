"""Eval case for running a whole notebook over MCP.

Its own suite rather than a case in `eval_notebook_cells`: the scorecard is different.
That suite requires `notebooks-add-cell` and grades cell authoring; this one requires
`notebooks-run` and grades whether one call carried both lanes of a notebook to a result.

To run it:
    hogli evals eval_notebook_run --eval run_whole_notebook
"""

from __future__ import annotations

from products.notebooks.evals.scorers import CellRunsCompleted, NotebookCreated
from products.notebooks.evals.seeders import seed_case_team
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_notebook_run(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            # The window is a variable rather than a literal, so the agent has to declare it
            # and then run the notebook — which is the pair this suite is about. Running the
            # cells one at a time would also finish, and the required-tool scorer is what
            # separates the two.
            name="run_whole_notebook",
            prompt=(
                "Create a notebook called 'Signup momentum'. Give it a variable for how many weeks "
                "to look back, set to 8. Add a SQL cell that returns weekly counts of `signed_up` "
                "events over that window, then a Python cell that reads that cell's dataframe and "
                "computes the week-over-week percentage change. Then run the whole notebook in one "
                "go and finish with a short markdown summary naming the week that grew the most."
            ),
            expected={
                "notebook_created": {},
                # Both lanes from one run: the SQL cell proves the direct path advanced without a
                # client polling it, the Python cell proves the kernel sandbox was provisioned and
                # reported back.
                "cell_runs_completed": {"node_types": ["hogql", "python"]},
            },
            setup=seed_case_team,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-notebook-run-cli",
        cases=cases,
        scorers=[
            RequiredToolCall({"notebooks-run"}),
            NotebookCreated(),
            CellRunsCompleted(),
        ],
        ctx=ctx,
    )
