import json
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from unittest.mock import MagicMock

from temporalio.exceptions import ApplicationError

from products.tasks.backend.exceptions import SandboxExecutionError
from products.tasks.backend.logic.services.publication_bundle import PublicationBundleError
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.models import TaskDraftPublication
from products.tasks.backend.temporal.publish_task_artifact import activities
from products.tasks.backend.temporal.publish_task_artifact.activities import PublishTaskArtifactInput


@pytest.mark.parametrize("failure", [None, "normalization", "path", "size", "transient", "bundle", "gate"])
def test_export_stops_agent_and_persists_deterministic_outcome(mocker, failure: str | None) -> None:
    publication = SimpleNamespace(
        id=UUID(int=2),
        team_id=1,
        caller_id=UUID(int=3),
        repository="example/repository",
        base_sha="a" * 40,
        commit_message="feat(tasks): publish a safe change",
        created_at=MagicMock(timestamp=lambda: 1),
        staged_run=SimpleNamespace(execution_run=SimpleNamespace(state={"sandbox_id": "sandbox-1"})),
    )
    sandbox = MagicMock()
    ok = ExecutionResult(stdout="", stderr="", exit_code=0)
    sandbox.stop_agent_server.return_value = sandbox.write_file.return_value = ok
    sandbox.execute.side_effect = lambda command, **_kwargs: ExecutionResult(
        stdout="",
        stderr="",
        exit_code=int(
            (failure == "normalization" and "python3" in command) or (failure == "gate" and "diff --check" in command)
        ),
    )
    bundle_path = (
        "/tmp/unsafe/publication.bundle"
        if failure == "path"
        else f"/tmp/tasks-draft-publications/{publication.id}-nonce/output/publication.bundle"
    )
    if failure == "size":
        sandbox.read_file_bytes.side_effect = ValueError("too large")
    elif failure == "transient":
        sandbox.read_file_bytes.side_effect = SandboxExecutionError(
            "provider unavailable", {}, cause=RuntimeError("try again")
        )
    else:
        sandbox.read_file_bytes.side_effect = [
            json.dumps({"bundle_path": bundle_path}).encode(),
            b"validated-bundle",
            b"",
        ]
    provider = MagicMock(get_by_id=MagicMock(return_value=sandbox))
    mocker.patch.object(activities, "uuid4", return_value=SimpleNamespace(hex="nonce"))
    mocker.patch.object(activities, "get_sandbox_class_for_sandbox_id", return_value=provider)
    mocker.patch.object(activities, "sandbox_repo_path", return_value="/workspace")
    mocker.patch.object(
        activities,
        "validate_publication_bundle",
        side_effect=PublicationBundleError("invalid") if failure == "bundle" else None,
        return_value=SimpleNamespace(artifact_head_sha="b" * 40, base_tree_sha="c" * 40, head_tree_sha="d" * 40),
    )
    record = mocker.patch.object(activities, "record_validated_bundle")
    block = mocker.patch.object(activities, "block_publication")
    mocker.patch.object(activities.object_storage, "write")
    mocker.patch.object(activities.object_storage, "read_bytes", return_value=b"validated-bundle")

    if failure == "transient":
        with pytest.raises(SandboxExecutionError):
            activities._export_and_store(cast(TaskDraftPublication, publication))
    elif failure:
        with pytest.raises(ApplicationError):
            activities._export_and_store(cast(TaskDraftPublication, publication))
    else:
        activities._export_and_store(cast(TaskDraftPublication, publication))

    expected_calls = (0, 1) if failure is None else (0, 0) if failure == "transient" else (1, 0)
    assert (block.call_count, record.call_count) == expected_calls


def test_activity_exports_before_calling_publication_service(mocker) -> None:
    input = PublishTaskArtifactInput(staged_run_id=UUID(int=1), publication_id=UUID(int=2))
    publication = SimpleNamespace(bundle_storage_ref=None, team_id=1, caller_id=UUID(int=3), id=input.publication_id)
    expected = SimpleNamespace(status="published")
    mocker.patch.object(activities, "_publication", return_value=publication)
    export = mocker.patch.object(activities, "_export_and_store")
    publish = mocker.patch.object(activities, "publish_publication", return_value=expected)

    assert activities.publish_task_artifact(input) == expected
    export.assert_called_once_with(publication)
    publish.assert_called_once_with(team_id=1, caller_id=UUID(int=3), publication_id=UUID(int=2))
