import hashlib
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import Mock

from pytest_mock import MockerFixture

from posthog.models.integration import Integration

from products.tasks.backend.logic.services.publication_base import TrustedBaseManifest, TrustedBaseTextBlob
from products.tasks.backend.logic.services.publication_gates import PublicationGatePolicyError
from products.tasks.backend.logic.services.publication_service import StagedDraftPublicationReplay
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.logic.services.staged_task_runs import DraftPublicationReservation
from products.tasks.backend.temporal.process_task.activities import export_draft_publication_bundle as activity_module


def _publication() -> activity_module._ActivityPublication:
    return activity_module._ActivityPublication(
        publication_id="publication-id",
        repository="PostHog/posthog",
        base_sha="a" * 40,
        base_branch="main",
        branch="codex/" + "b" * 32,
        commit_message="chore(tasks): create draft publication",
        author_name="PostHog Tasks",
        author_email="tasks@posthog.com",
        commit_timestamp=1,
        pr_title="Draft",
        pr_body="Body",
        integration=cast(Integration, object()),
    )


def _sandbox(mocker: MockerFixture) -> Mock:
    sandbox = mocker.Mock(spec=activity_module.ModalSandbox)
    sandbox.stop_agent_server.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    sandbox.write_file.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    return sandbox


def _patch_publication(mocker: MockerFixture) -> None:
    publication = _publication()
    mocker.patch.object(activity_module, "_run_required_publication_gates")
    mocker.patch.object(activity_module, "_activity_publication", return_value=publication)
    mocker.patch.object(
        activity_module,
        "reserve_staged_draft_publication",
        return_value=DraftPublicationReservation(
            publication_id=publication.publication_id,
            repository=publication.repository,
            base_sha=publication.base_sha,
            base_branch="main",
            branch=publication.branch,
        ),
    )
    mocker.patch.object(
        activity_module,
        "get_staged_draft_publication_replay",
        return_value=StagedDraftPublicationReplay(
            publication_id=publication.publication_id,
            status="reserved",
            bundle_storage_path=None,
            bundle_head_sha=None,
            bundle_sha256=None,
            bundle_byte_count=None,
            commit_sha=None,
            pr_number=None,
            pr_url=None,
        ),
    )


def test_runs_only_protected_base_argv_gate_without_agent_environment(mocker: MockerFixture) -> None:
    sandbox = _sandbox(mocker)
    publication = _publication()
    policy_base = object()
    load_base = mocker.patch.object(activity_module, "_load_base", return_value=policy_base)
    mocker.patch.object(activity_module, "resolve_publication_gate_policy", return_value=object())
    mocker.patch.object(activity_module, "assert_publication_gate_paths_safe")
    mocker.patch.object(
        activity_module,
        "record_publication_gate_policy",
        return_value=(SimpleNamespace(gate_key="gate", label="focused tests", argv=("pytest", "-q")),),
    )
    mocker.patch.object(
        activity_module,
        "get_publication_gate_status",
        return_value=SimpleNamespace(gates=()),
    )
    recorded = mocker.patch.object(activity_module, "record_publication_gate_result")

    activity_module._run_required_publication_gates(sandbox, "run", publication, ("products/tasks/example.py",))

    assert load_base.call_args.args[1] == (activity_module.PUBLICATION_GATE_POLICY_PATH,)
    command = sandbox.execute.call_args.args[0]
    assert "env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent" in command
    assert "pytest" in command
    assert sandbox.execute.call_args.kwargs["timeout_seconds"] == 8 * 60
    recorded.assert_called_once()


def test_rejects_protected_candidate_path_before_executing_gate(mocker: MockerFixture) -> None:
    sandbox = _sandbox(mocker)
    publication = _publication()
    policy_base = TrustedBaseManifest(
        repository=publication.repository,
        base_sha=publication.base_sha,
        tree_sha="b" * 40,
        entries=(),
        old_text_blobs=(
            TrustedBaseTextBlob(
                path=activity_module.PUBLICATION_GATE_POLICY_PATH,
                object_sha="c" * 40,
                text=(
                    '{"version":2,"gates":[{"label":"tests","argv":["pytest"]}],'
                    '"protected_path_prefixes":["package.json"]}'
                ),
            ),
        ),
    )
    mocker.patch.object(activity_module, "_load_base", return_value=policy_base)

    with pytest.raises(PublicationGatePolicyError, match="publication_gate_protected_path_changed"):
        activity_module._run_required_publication_gates(sandbox, "run", publication, ("package.json",))

    sandbox.execute.assert_not_called()


def test_rejects_unsupported_provider_before_stop_or_storage(mocker: MockerFixture) -> None:
    sandbox = mocker.Mock()
    _patch_publication(mocker)
    mocker.patch.object(
        activity_module, "get_sandbox_class_for_sandbox_id", **{"return_value.get_by_id.return_value": sandbox}
    )
    storage = mocker.patch.object(activity_module.object_storage, "write")

    with pytest.raises(RuntimeError, match="cannot export"):
        activity_module.export_draft_publication_bundle_now(
            activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
        )

    sandbox.stop_agent_server.assert_not_called()
    storage.assert_not_called()


def test_reserves_before_reading_the_initial_replay(mocker: MockerFixture) -> None:
    events: list[str] = []
    publication = _publication()
    mocker.patch.object(activity_module, "_activity_publication", return_value=publication)

    def reserve(_run_id: str) -> DraftPublicationReservation:
        events.append("reserve")
        return DraftPublicationReservation(
            publication_id=publication.publication_id,
            repository=publication.repository,
            base_sha=publication.base_sha,
            base_branch="main",
            branch=publication.branch,
        )

    def replay(_run_id: str) -> StagedDraftPublicationReplay:
        events.append("replay")
        return StagedDraftPublicationReplay(
            publication_id=publication.publication_id,
            status="reserved",
            bundle_storage_path=None,
            bundle_head_sha=None,
            bundle_sha256=None,
            bundle_byte_count=None,
            commit_sha=None,
            pr_number=None,
            pr_url=None,
        )

    mocker.patch.object(activity_module, "reserve_staged_draft_publication", side_effect=reserve)
    mocker.patch.object(
        activity_module,
        "get_staged_draft_publication_replay",
        side_effect=replay,
    )
    mocker.patch.object(
        activity_module,
        "get_sandbox_class_for_sandbox_id",
        **{"return_value.get_by_id.return_value": mocker.Mock()},
    )

    with pytest.raises(RuntimeError, match="cannot export"):
        activity_module.export_draft_publication_bundle_now(
            activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
        )

    assert events == ["reserve", "replay"]


def test_stops_before_writing_only_server_script_and_returns_no_bundle_bytes(mocker: MockerFixture) -> None:
    payload = b"bundle"
    sandbox = _sandbox(mocker)
    mocker.patch.object(activity_module, "uuid4", return_value=SimpleNamespace(hex="x"))
    sandbox.read_file_bytes.side_effect = [
        b'{"bundle_path":"/tmp/tasks-draft-publications/x/publication-safe/publication.bundle"}',
        payload,
    ]
    _patch_publication(mocker)
    mocker.patch.object(
        activity_module, "get_sandbox_class_for_sandbox_id", **{"return_value.get_by_id.return_value": sandbox}
    )
    mocker.patch.object(
        activity_module,
        "inspect_publication_bundle",
        return_value=SimpleNamespace(head_commit="c" * 40, changed_paths=("x.txt",)),
    )
    mocker.patch.object(activity_module, "_load_base", return_value=object())
    validated = SimpleNamespace(
        commit_message="m", pr_title="t", pr_body="b", unified_diff="", files=(), added_text_blobs=()
    )
    mocker.patch.object(activity_module, "validate_publication_bundle", return_value=validated)
    scan = mocker.patch.object(activity_module, "_scan")
    mocker.patch.object(activity_module.object_storage, "read_bytes", side_effect=[None, payload])
    mocker.patch.object(activity_module.object_storage, "write")
    record = mocker.patch.object(activity_module, "record_staged_draft_publication_bundle")
    mocker.patch.object(
        activity_module,
        "publish_staged_draft_publication",
        return_value=SimpleNamespace(commit_sha="d" * 40, pr_number=1, pr_url="https://example.com/pr/1"),
    )

    output = activity_module.export_draft_publication_bundle_now(
        activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
    )

    assert sandbox.stop_agent_server.call_args_list < sandbox.write_file.call_args_list
    assert sandbox.write_file.call_args.args[1].startswith(b"import ")
    assert output.bundle_sha256 == hashlib.sha256(payload).hexdigest()
    assert output.pr_url == "https://example.com/pr/1"
    assert not hasattr(output, "bundle_bytes")
    assert scan.call_count == 2
    record.assert_called_once()


def test_inspection_failure_prevents_scanning_upload_and_record(mocker: MockerFixture) -> None:
    sandbox = _sandbox(mocker)
    mocker.patch.object(activity_module, "uuid4", return_value=SimpleNamespace(hex="x"))
    sandbox.read_file_bytes.side_effect = [
        b'{"bundle_path":"/tmp/tasks-draft-publications/x/publication-safe/publication.bundle"}',
        b"bundle",
    ]
    _patch_publication(mocker)
    mocker.patch.object(
        activity_module, "get_sandbox_class_for_sandbox_id", **{"return_value.get_by_id.return_value": sandbox}
    )
    mocker.patch.object(activity_module, "inspect_publication_bundle", side_effect=ValueError("invalid bundle"))
    upload = mocker.patch.object(activity_module.object_storage, "write")
    record = mocker.patch.object(activity_module, "record_staged_draft_publication_bundle")

    with pytest.raises(ValueError, match="invalid bundle"):
        activity_module.export_draft_publication_bundle_now(
            activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
        )

    upload.assert_not_called()
    record.assert_not_called()


def test_invalid_normalized_bundle_prevents_gate_execution(mocker: MockerFixture) -> None:
    sandbox = _sandbox(mocker)
    mocker.patch.object(activity_module, "uuid4", return_value=SimpleNamespace(hex="x"))
    sandbox.read_file_bytes.side_effect = [
        b'{"bundle_path":"/tmp/tasks-draft-publications/x/publication-safe/publication.bundle"}',
        b"bundle",
    ]
    _patch_publication(mocker)
    mocker.patch.object(
        activity_module, "get_sandbox_class_for_sandbox_id", **{"return_value.get_by_id.return_value": sandbox}
    )
    mocker.patch.object(
        activity_module,
        "inspect_publication_bundle",
        return_value=SimpleNamespace(head_commit="c" * 40, changed_paths=("package.json",)),
    )
    mocker.patch.object(activity_module, "_load_base", return_value=object())
    mocker.patch.object(activity_module, "validate_publication_bundle", side_effect=ValueError("invalid bundle"))
    run_gates = mocker.patch.object(activity_module, "_run_required_publication_gates")

    with pytest.raises(ValueError, match="invalid bundle"):
        activity_module.export_draft_publication_bundle_now(
            activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
        )

    run_gates.assert_not_called()


def test_rejects_metadata_path_traversal() -> None:
    with pytest.raises(RuntimeError, match="unsafe bundle path"):
        activity_module._bundle_path_from_metadata(
            "/tmp/tasks-draft-publications/random",
            {"bundle_path": "/tmp/tasks-draft-publications/random/../other/publication.bundle"},
        )


def test_finalized_replay_returns_authoritative_refs_without_sandbox_or_storage(mocker: MockerFixture) -> None:
    mocker.patch.object(
        activity_module,
        "reserve_staged_draft_publication",
        side_effect=activity_module.TaskInvalidStateError("finalized", {}, RuntimeError("finalized")),
    )
    mocker.patch.object(
        activity_module,
        "get_staged_draft_publication_replay",
        return_value=StagedDraftPublicationReplay(
            publication_id="publication-id",
            status="finalized",
            bundle_storage_path="tasks/draft-publications/id/hash.bundle",
            bundle_head_sha="a" * 40,
            bundle_sha256="b" * 64,
            bundle_byte_count=1,
            commit_sha="c" * 40,
            pr_number=1,
            pr_url="https://example.com/pr/1",
        ),
    )
    sandbox = mocker.patch.object(activity_module, "get_sandbox_class_for_sandbox_id")
    storage = mocker.patch.object(activity_module.object_storage, "read_bytes")

    output = activity_module.export_draft_publication_bundle_now(
        activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
    )

    assert output.pr_url == "https://example.com/pr/1"
    assert output.publication_id == "publication-id"
    sandbox.assert_not_called()
    storage.assert_not_called()


def test_uploaded_replay_validates_stored_bundle_without_sandbox(mocker: MockerFixture) -> None:
    payload = b"bundle"
    publication = _publication()
    mocker.patch.object(activity_module, "_activity_publication", return_value=publication)
    mocker.patch.object(
        activity_module,
        "reserve_staged_draft_publication",
        side_effect=activity_module.TaskInvalidStateError("uploaded", {}, RuntimeError("uploaded")),
    )
    mocker.patch.object(
        activity_module,
        "get_staged_draft_publication_replay",
        return_value=StagedDraftPublicationReplay(
            publication_id="publication-id",
            status="uploaded",
            bundle_storage_path="tasks/draft-publications/id/hash.bundle",
            bundle_head_sha="a" * 40,
            bundle_sha256=hashlib.sha256(payload).hexdigest(),
            bundle_byte_count=len(payload),
            commit_sha=None,
            pr_number=None,
            pr_url=None,
        ),
    )
    sandbox = mocker.patch.object(activity_module, "get_sandbox_class_for_sandbox_id")
    mocker.patch.object(activity_module.object_storage, "read_bytes", return_value=payload)
    mocker.patch.object(
        activity_module,
        "inspect_publication_bundle",
        return_value=SimpleNamespace(head_commit="a" * 40, changed_paths=("x.txt",)),
    )
    mocker.patch.object(activity_module, "_load_base", return_value=object())
    validated = SimpleNamespace(
        commit_message="m", pr_title="t", pr_body="b", unified_diff="", files=(), added_text_blobs=()
    )
    mocker.patch.object(activity_module, "validate_publication_bundle", return_value=validated)
    mocker.patch.object(activity_module, "_scan")
    mocker.patch.object(
        activity_module,
        "publish_staged_draft_publication",
        return_value=SimpleNamespace(commit_sha="c" * 40, pr_number=1, pr_url="https://example.com/pr/1"),
    )

    output = activity_module.export_draft_publication_bundle_now(
        activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
    )

    assert output.commit_sha == "c" * 40
    sandbox.assert_not_called()


def test_unknown_replay_uses_expiry_reconciliation_without_exporting_again(mocker: MockerFixture) -> None:
    payload = b"bundle"
    publication = _publication()
    activity_publication = mocker.patch.object(activity_module, "_activity_publication", return_value=publication)
    mocker.patch.object(
        activity_module,
        "reserve_staged_draft_publication",
        side_effect=activity_module.TaskInvalidStateError("expired", {}, RuntimeError("expired")),
    )
    mocker.patch.object(
        activity_module,
        "get_staged_draft_publication_replay",
        return_value=StagedDraftPublicationReplay(
            publication_id="publication-id",
            status="publication_unknown",
            bundle_storage_path="tasks/draft-publications/id/hash.bundle",
            bundle_head_sha="a" * 40,
            bundle_sha256=hashlib.sha256(payload).hexdigest(),
            bundle_byte_count=len(payload),
            commit_sha=None,
            pr_number=None,
            pr_url=None,
        ),
    )
    sandbox = mocker.patch.object(activity_module, "get_sandbox_class_for_sandbox_id")
    mocker.patch.object(activity_module.object_storage, "read_bytes", return_value=payload)
    mocker.patch.object(
        activity_module,
        "inspect_publication_bundle",
        return_value=SimpleNamespace(head_commit="a" * 40, changed_paths=("x.txt",)),
    )
    mocker.patch.object(activity_module, "_load_base", return_value=object())
    validated = SimpleNamespace(
        commit_message="m", pr_title="t", pr_body="b", unified_diff="", files=(), added_text_blobs=()
    )
    mocker.patch.object(activity_module, "validate_publication_bundle", return_value=validated)
    mocker.patch.object(activity_module, "_scan")
    publish = mocker.patch.object(
        activity_module,
        "publish_staged_draft_publication",
        return_value=SimpleNamespace(commit_sha="c" * 40, pr_number=1, pr_url="https://example.com/pr/1"),
    )

    output = activity_module.export_draft_publication_bundle_now(
        activity_module.ExportDraftPublicationBundleInput(sandbox_id="sandbox", run_id="run")
    )

    assert output.pr_number == 1
    activity_publication.assert_called_once_with("run", mode="reconcile_after_expiry")
    sandbox.assert_not_called()
    publish.assert_called_once()
