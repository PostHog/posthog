"""Payloads the whole-notebook run workflow and its activities exchange.

A leaf module on purpose: `temporal/client.py` starts the workflow and must not pull in the
activity implementations, which reach back into the dispatch code that starts *cell*
workflows through that same client.
"""

from typing import Literal

from posthog.dataclasses import frozen

# The whole run's budget. A run that outlives it is stuck rather than slow: MAX_NOTEBOOK_CELLS
# is 50 and each cell carries its own watchdog, so nothing correct reaches an hour of *no*
# cell reaching a terminal state. The workflow measures it itself, so the run row still gets a
# terminal status and a reason, which a Temporal run timeout could not deliver.
NOTEBOOK_RUN_BUDGET_SECONDS = 60 * 60


@frozen
class NotebookRunInput:
    notebook_run_id: str
    team_id: int


@frozen
class NotebookRunCellInput:
    notebook_run_id: str
    team_id: int
    index: int


@frozen
class CellDispatched:
    # `dispatched` means a cell is in flight; every other outcome ends the run.
    outcome: Literal["dispatched", "finished", "interrupted", "failed"]
    node_run_id: str | None = None
    node_id: str | None = None
    error: str | None = None


@frozen
class CellRunLookup:
    node_run_id: str
    team_id: int


@frozen
class CellStatus:
    status: str
    error: str | None = None


@frozen
class NotebookRunFinish:
    notebook_run_id: str
    team_id: int
    status: str
    failed_node_id: str | None = None
    error: str | None = None
