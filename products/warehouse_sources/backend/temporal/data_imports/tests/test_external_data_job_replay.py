"""Replay compatibility of `external-data-job`.

The histories under `histories/` were recorded from the workflow as it was before the per-run
activities were folded together (billing check into job creation, lock release into the finalizer,
the templates activity gated). On deploy every in-flight execution replays its recorded history
against the new code, so each of these must replay without a non-determinism error: the new code
must keep issuing the old command sequence wherever the recorded activity payloads or missing patch
markers say so.
"""

from pathlib import Path

import pytest
from unittest import mock

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from products.warehouse_sources.backend.temporal.data_imports.external_data_job import ExternalDataJobWorkflow

HISTORIES = Path(__file__).parent / "histories"


@pytest.mark.asyncio
@pytest.mark.parametrize("history_name", sorted(path.stem for path in HISTORIES.glob("*.json")))
async def test_pre_change_history_replays(history_name: str) -> None:
    history = WorkflowHistory.from_json("external-data-job", (HISTORIES / f"{history_name}.json").read_text())

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_data_import_finished_metric"
    ):
        await Replayer(
            workflows=[ExternalDataJobWorkflow],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)
