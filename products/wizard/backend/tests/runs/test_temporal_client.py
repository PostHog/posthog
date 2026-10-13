from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from products.wizard.backend.temporal import client as temporal_client
from products.wizard.backend.temporal.contracts import WizardRunActivityInput
from products.wizard.backend.temporal.errors import WizardTemporalError
from products.wizard.backend.temporal.workflows.execute_run import ExecuteWizardRunWorkflow


def test_start_wizard_run_workflow_uses_stable_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    start_workflow = AsyncMock()
    connect = AsyncMock(return_value=SimpleNamespace(start_workflow=start_workflow))
    monkeypatch.setattr(temporal_client, "async_connect", connect)
    input = WizardRunActivityInput(team_id=1, run_id=uuid4())

    temporal_client.start_wizard_run_workflow(input)

    start_workflow.assert_awaited_once_with(
        ExecuteWizardRunWorkflow.get_name(),
        input,
        id=ExecuteWizardRunWorkflow.workflow_id_for(input.run_id),
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        task_queue=settings.WIZARD_TASK_QUEUE,
        retry_policy=temporal_client.WORKFLOW_RETRY_POLICY,
    )


def test_start_wizard_run_workflow_accepts_duplicate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    input = WizardRunActivityInput(team_id=1, run_id=uuid4())
    start_workflow = AsyncMock(
        side_effect=WorkflowAlreadyStartedError(
            ExecuteWizardRunWorkflow.workflow_id_for(input.run_id),
            ExecuteWizardRunWorkflow.get_name(),
        )
    )
    connect = AsyncMock(return_value=SimpleNamespace(start_workflow=start_workflow))
    monkeypatch.setattr(temporal_client, "async_connect", connect)

    temporal_client.start_wizard_run_workflow(input)


def test_start_wizard_run_workflow_translates_rpc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    input = WizardRunActivityInput(team_id=1, run_id=uuid4())
    start_workflow = AsyncMock(side_effect=RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""))
    connect = AsyncMock(return_value=SimpleNamespace(start_workflow=start_workflow))
    monkeypatch.setattr(temporal_client, "async_connect", connect)

    with pytest.raises(WizardTemporalError):
        temporal_client.start_wizard_run_workflow(input)


def test_start_wizard_run_workflow_translates_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    input = WizardRunActivityInput(team_id=1, run_id=uuid4())
    connect = AsyncMock(side_effect=RuntimeError("connection closed"))
    monkeypatch.setattr(temporal_client, "async_connect", connect)

    with pytest.raises(WizardTemporalError):
        temporal_client.start_wizard_run_workflow(input)


def test_cancel_wizard_run_workflow_accepts_missing_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = AsyncMock(side_effect=RPCError("not found", RPCStatusCode.NOT_FOUND, b""))
    handle = MagicMock(cancel=cancel)
    connect = AsyncMock(return_value=MagicMock(get_workflow_handle=MagicMock(return_value=handle)))
    monkeypatch.setattr(temporal_client, "async_connect", connect)

    temporal_client.cancel_wizard_run_workflow(uuid4())


def test_cancel_wizard_run_workflow_translates_rpc_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = AsyncMock(side_effect=RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""))
    handle = MagicMock(cancel=cancel)
    connect = AsyncMock(return_value=MagicMock(get_workflow_handle=MagicMock(return_value=handle)))
    monkeypatch.setattr(temporal_client, "async_connect", connect)

    with pytest.raises(WizardTemporalError):
        temporal_client.cancel_wizard_run_workflow(uuid4())
