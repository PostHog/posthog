"""Open-ended eval cases for churn analysis in a notebook over MCP.

Unlike ``eval_notebook_cells``, these cases name only the question, not the cells. They
check that the agent turns a churn-prediction request into a notebook that pulls behavioural
signals with SQL, carries the analysis into Python, and lands on a conclusion — the shape of
a real analysis, graded qualitatively rather than by matching an exact query.

Each case is seeded by ``seed_churn_signal``, which plants a small cohort of accounts that
were power users early in the demo window and then went completely silent — the textbook
churn shape. That gives the run a synthetic ground truth to grade the prediction against.

Four layers grade each case:

- ``NotebookCreated`` / ``CellRunsCompleted`` — the outcome, read from the database: a markdown
  notebook exists, and both a SQL (``hogql``) and a Python cell reached a completed run. This is
  what proves the agent used *both* lanes rather than doing everything in one.
- ``NotebookApproachQuality`` — the approach, an LLM judge over the cells the agent authored:
  did it pull the right behavioural signals and reason its way to a churn conclusion.
- ``ChurnCohortSurfaced`` — the prediction itself: what fraction of the planted silent accounts
  the notebook actually named as at-risk.

Because these cases need a completed Python run, run them on docker:
    hogli evals eval_notebook_analysis --provider docker
    hogli evals eval_notebook_analysis --eval churn_from_file_sharing --provider docker
"""

from __future__ import annotations

from products.notebooks.evals.scorers import (
    CellRunsCompleted,
    ChurnCohortSurfaced,
    NotebookApproachQuality,
    NotebookCreated,
)
from products.notebooks.evals.seeders import seed_churn_signal
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall

# Both lanes must complete: the SQL cell pulls the behavioural signals, the Python cell does the
# churn analysis over them. Naming both is what separates "wrote a python cell" from "the kernel
# ran it", and it is how these cases assert the agent used SQL *and* Python.
_SQL_AND_PYTHON = {"node_types": ["hogql", "python"]}


async def eval_notebook_analysis(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="churn_from_file_sharing",
            prompt=(
                "I want to predict churn for our file-sharing feature based on how people use it. "
                "Create a notebook that pulls each account's file-sharing and download behaviour "
                "with SQL, then works out in Python which accounts look most likely to churn and "
                "why. Finish with a short summary of the signals that matter most."
            ),
            expected={
                "notebook_created": {},
                "cell_runs_completed": _SQL_AND_PYTHON,
                "churn_cohort_surfaced": {},
                "notebook_approach_quality": {
                    "approach": (
                        "Uses SQL to pull per-account file-sharing engagement from behavioural events "
                        "such as shared_file_link, downloaded_file, and uploaded_file, with enough "
                        "history to show a trend (for example weekly counts or recent vs earlier "
                        "activity). Carries those dataframes into Python to derive a churn signal — for "
                        "instance flagging accounts whose sharing or downloading has fallen off, or "
                        "scoring/ranking accounts by risk — rather than eyeballing raw rows. Ends with a "
                        "conclusion that names which behavioural signals point to churn."
                    )
                },
            },
            setup=seed_churn_signal,
        ),
        SandboxedEvalCase(
            name="churn_from_upload_activity",
            prompt=(
                "Create a notebook to predict which users are likely to churn based on their "
                "file-upload behaviour over time. Use SQL to get weekly upload activity per user, "
                "then use Python to spot the accounts whose usage is trailing off and rank them by "
                "churn risk. Wrap up with a markdown summary of what you found."
            ),
            expected={
                "notebook_created": {},
                "cell_runs_completed": _SQL_AND_PYTHON,
                "churn_cohort_surfaced": {},
                "notebook_approach_quality": {
                    "approach": (
                        "Uses SQL to pull weekly uploaded_file activity per account or user across "
                        "several weeks, so a trend is visible. Uses Python over that dataframe to detect "
                        "declining usage — comparing recent weeks against earlier ones, or fitting a "
                        "slope — and ranks or flags the accounts most at risk. Ends with a summary that "
                        "explains which accounts look most likely to churn and on what basis."
                    )
                },
            },
            setup=seed_churn_signal,
        ),
        SandboxedEvalCase(
            name="churn_open_ended",
            prompt=(
                "I want to predict churn based on user behaviour. Build a notebook that figures out "
                "which behavioural signals separate users who stick around from users who leave, and "
                "use them to flag the accounts most at risk. Explain your approach as you go."
            ),
            expected={
                "notebook_created": {},
                "cell_runs_completed": _SQL_AND_PYTHON,
                "churn_cohort_surfaced": {},
                "notebook_approach_quality": {
                    "approach": (
                        "Chooses sensible behavioural churn signals for a file-storage product on its own "
                        "— activity frequency (logged_in, uploaded_file, downloaded_file, shared_file_link) "
                        "and negative signals (downgraded_plan, activity dropping to zero) — and pulls them "
                        "with SQL. Uses Python to compare retained versus lapsed users on those signals, or "
                        "to build a risk score, rather than asserting a churn definition without deriving it. "
                        "Explains the reasoning and flags the most at-risk accounts with a conclusion a "
                        "reader can act on."
                    )
                },
            },
            setup=seed_churn_signal,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-notebook-analysis-cli",
        cases=cases,
        scorers=[
            RequiredToolCall({"notebooks-add-cell"}),
            NotebookCreated(),
            CellRunsCompleted(),
            ChurnCohortSurfaced(),
            NotebookApproachQuality(),
        ],
        ctx=ctx,
    )
