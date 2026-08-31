"""Export, verify, and persist a normalized Tasks draft publication bundle."""

from __future__ import annotations

import json
import shlex
import hashlib
from pathlib import Path
from typing import Literal
from uuid import uuid4

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.integration.github import GitHubIntegration
from posthog.storage import object_storage
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.publication_base import TrustedBaseManifest, load_trusted_base_manifest
from products.tasks.backend.logic.services.publication_broker import (
    PublicationScanRequest,
    PublicationTextFile,
    scan_draft_publication,
)
from products.tasks.backend.logic.services.publication_bundle import (
    PublicationBundlePlan,
    ValidatedPublicationBundle,
    build_publication_bundle_script,
    inspect_publication_bundle,
    validate_publication_bundle,
)
from products.tasks.backend.logic.services.publication_gate_ledger import (
    get_publication_gate_status,
    record_publication_gate_policy,
    record_publication_gate_result,
)
from products.tasks.backend.logic.services.publication_gates import (
    PUBLICATION_GATE_POLICY_PATH,
    assert_publication_gate_paths_safe,
    resolve_publication_gate_policy,
)
from products.tasks.backend.logic.services.publication_service import (
    PublicationProposal,
    StagedDraftPublicationReplay,
    get_staged_draft_publication_replay,
    publish_staged_draft_publication,
)
from products.tasks.backend.logic.services.publication_transport import NormalizedTreeOperation
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id, sandbox_repo_path
from products.tasks.backend.logic.services.staged_task_runs import (
    StagedPublicationValidationMode,
    record_staged_draft_publication_bundle,
    reserve_staged_draft_publication,
    with_validated_staged_draft_publication,
)
from products.tasks.backend.models import (
    Task,
    TaskDraftPublication,
    TaskPublicationLease,
    TaskRun,
    TaskStagedRunTransition,
)

_MAX_BUNDLE_BYTES = 20 * 1024 * 1024
_MAX_METADATA_BYTES = 4096
_SANDBOX_TIMEOUT_SECONDS = 60
_PUBLICATION_GATE_TIMEOUT_SECONDS = 8 * 60
_NormalizedTreeMode = Literal["100644", "100755"]


@frozen
class ExportDraftPublicationBundleInput:
    sandbox_id: str
    run_id: str


@frozen
class ExportDraftPublicationBundleOutput:
    publication_id: str
    storage_path: str
    bundle_sha256: str
    bundle_head_sha: str
    bundle_byte_count: int
    commit_sha: str
    pr_number: int
    pr_url: str


@frozen
class _ActivityPublication:
    publication_id: str
    repository: str
    base_sha: str
    base_branch: str
    branch: str
    commit_message: str
    author_name: str
    author_email: str
    commit_timestamp: int
    pr_title: str
    pr_body: str
    integration: Integration


@frozen
class _RequiredBundleMetadata:
    storage_path: str
    bundle_head_sha: str
    bundle_sha256: str
    bundle_byte_count: int


def _activity_publication(
    run_id: str, *, mode: StagedPublicationValidationMode = "start_mutation"
) -> _ActivityPublication:
    def _read(
        integration: Integration,
        _task: Task,
        _source: TaskRun,
        _transition: TaskStagedRunTransition,
        _successor: TaskRun,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> _ActivityPublication:
        return _ActivityPublication(
            publication_id=str(publication.id),
            repository=str(lease.repository),
            base_sha=str(lease.base_sha),
            base_branch=publication.base_branch,
            branch=str(publication.branch),
            commit_message=publication.commit_message,
            author_name=publication.commit_author_name,
            author_email=publication.commit_author_email,
            commit_timestamp=publication.commit_timestamp,
            pr_title=publication.pr_title,
            pr_body=publication.pr_body,
            integration=integration,
        )

    return with_validated_staged_draft_publication(run_id, _read, mode=mode)


def _load_base(publication: _ActivityPublication, changed_paths: tuple[str, ...]) -> TrustedBaseManifest:
    client = GitHubIntegration(publication.integration, source="tasks_publication")
    return load_trusted_base_manifest(
        client, repository=publication.repository, base_sha=publication.base_sha, changed_paths=changed_paths
    )


def _run_required_publication_gates(
    sandbox: ModalSandbox,
    run_id: str,
    publication: _ActivityPublication,
    changed_paths: tuple[str, ...],
) -> None:
    """Execute only protected-base argv gates after the agent server is stopped."""
    policy_base = _load_base(publication, (PUBLICATION_GATE_POLICY_PATH,))
    policy = resolve_publication_gate_policy(policy_base)
    assert_publication_gate_paths_safe(policy, changed_paths)
    gates = record_publication_gate_policy(run_id, policy)
    status = get_publication_gate_status(run_id)
    passed = {label for label, gate_status in status.gates if gate_status == "passed"} if status is not None else set()
    workspace = sandbox_repo_path(publication.repository)
    for gate in gates:
        if gate.label in passed:
            continue
        command = " ".join(
            [
                "env",
                "-i",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "HOME=/nonexistent",
                "/bin/sh",
                "-c",
                shlex.quote('cd -- "$1" && shift && exec "$@"'),
                "sh",
                shlex.quote(workspace),
                *(shlex.quote(argument) for argument in gate.argv),
            ]
        )
        result = sandbox.execute(command, timeout_seconds=_PUBLICATION_GATE_TIMEOUT_SECONDS)
        output = (result.stdout + "\n" + result.stderr).encode("utf-8", errors="replace")
        record_publication_gate_result(run_id, gate, exit_code=result.exit_code, output=output)
        if result.exit_code != 0:
            raise RuntimeError(f"Required publication gate failed: {gate.label}")


def _scan(publication: _ActivityPublication, bundle: ValidatedPublicationBundle) -> None:
    modes = {file.path: file.mode for file in bundle.files}
    scan_draft_publication(
        PublicationScanRequest(
            branch=publication.branch,
            commit_message=bundle.commit_message,
            pr_title=bundle.pr_title,
            pr_body=bundle.pr_body,
            unified_diff=bundle.unified_diff,
            changed_paths=tuple(file.path for file in bundle.files),
            expected_added_paths=tuple(blob.path for blob in bundle.added_text_blobs),
            added_files=tuple(
                PublicationTextFile(path=blob.path, mode=modes[blob.path], object_type="blob", content=blob.text)
                for blob in bundle.added_text_blobs
            ),
        )
    )


def _proposal(bundle: ValidatedPublicationBundle) -> PublicationProposal:
    blobs = {blob.path: blob.text for blob in bundle.added_text_blobs}
    operations: list[NormalizedTreeOperation] = []
    for file in bundle.files:
        mode = _normalized_tree_mode(file.mode)
        if file.status == "deleted":
            operations.append(NormalizedTreeOperation(path=file.path, mode=mode, content=None))
            continue
        text = blobs.get(file.path)
        if text is None:
            raise RuntimeError("Validated publication bundle is missing normalized text")
        operations.append(NormalizedTreeOperation(path=file.path, mode=mode, content=text.encode("utf-8")))
    return PublicationProposal(operations=tuple(operations))


def _normalized_tree_mode(mode: str) -> _NormalizedTreeMode:
    if mode == "100644":
        return "100644"
    if mode == "100755":
        return "100755"
    raise RuntimeError("Validated publication bundle has an unsafe file mode")


def _plan(publication: _ActivityPublication, export_root: Path) -> PublicationBundlePlan:
    return PublicationBundlePlan(
        workspace_path=Path(sandbox_repo_path(publication.repository)),
        export_root=export_root,
        repository=publication.repository,
        base_commit=publication.base_sha,
        commit_message=publication.commit_message,
        author_name=publication.author_name,
        author_email=publication.author_email,
        commit_timestamp=publication.commit_timestamp,
        pr_title=publication.pr_title,
        pr_body=publication.pr_body,
    )


def _output(
    run_id: str,
    publication: _ActivityPublication,
    replay: StagedDraftPublicationReplay,
    bundle: ValidatedPublicationBundle,
) -> ExportDraftPublicationBundleOutput:
    metadata = _required_bundle_metadata(replay)
    published = publish_staged_draft_publication(run_id, _proposal(bundle))
    return ExportDraftPublicationBundleOutput(
        publication_id=publication.publication_id,
        storage_path=metadata.storage_path,
        bundle_sha256=metadata.bundle_sha256,
        bundle_head_sha=metadata.bundle_head_sha,
        bundle_byte_count=metadata.bundle_byte_count,
        commit_sha=published.commit_sha,
        pr_number=published.pr_number,
        pr_url=published.pr_url,
    )


def _required_bundle_metadata(replay: StagedDraftPublicationReplay) -> _RequiredBundleMetadata:
    storage_path = replay.bundle_storage_path
    bundle_head_sha = replay.bundle_head_sha
    bundle_sha256 = replay.bundle_sha256
    bundle_byte_count = replay.bundle_byte_count
    if not storage_path or not bundle_head_sha or not bundle_sha256 or not bundle_byte_count:
        raise RuntimeError("Draft publication replay is missing bundle metadata")
    return _RequiredBundleMetadata(
        storage_path=storage_path,
        bundle_head_sha=bundle_head_sha,
        bundle_sha256=bundle_sha256,
        bundle_byte_count=bundle_byte_count,
    )


def _cleanup(sandbox: ModalSandbox, directory: str) -> None:
    try:
        sandbox.execute(f"rm -rf -- {shlex.quote(directory)}", timeout_seconds=_SANDBOX_TIMEOUT_SECONDS)
    except Exception:
        pass


def _replay_after_expiry_validation_mode(status: str) -> StagedPublicationValidationMode | None:
    if status in {
        TaskDraftPublication.Status.BRANCH_CREATING,
        TaskDraftPublication.Status.BRANCH_CREATED,
        TaskDraftPublication.Status.PR_CREATING,
        TaskDraftPublication.Status.PUBLISHED,
        TaskDraftPublication.Status.PUBLICATION_UNKNOWN,
    }:
        return "reconcile_after_expiry"
    return None


def _replay_activity_publication(run_id: str, status: str) -> _ActivityPublication:
    reconciliation_mode = _replay_after_expiry_validation_mode(status)
    if reconciliation_mode is not None:
        return _activity_publication(run_id, mode=reconciliation_mode)
    return _activity_publication(run_id, mode="in_flight_mutation")


def _bundle_path_from_metadata(directory: str, metadata: object) -> str:
    bundle_path = metadata.get("bundle_path") if isinstance(metadata, dict) else None
    if not isinstance(bundle_path, str):
        raise RuntimeError("Normalization returned an unsafe bundle path")
    root = Path(directory)
    candidate = Path(bundle_path)
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise RuntimeError("Normalization returned an unsafe bundle path") from error
    if (
        not candidate.is_absolute()
        or len(relative.parts) != 2
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not relative.parts[0].startswith("publication-")
        or relative.parts[1] != "publication.bundle"
    ):
        raise RuntimeError("Normalization returned an unsafe bundle path")
    return bundle_path


def export_draft_publication_bundle_now(input: ExportDraftPublicationBundleInput) -> ExportDraftPublicationBundleOutput:
    try:
        reservation = reserve_staged_draft_publication(input.run_id)
    except TaskInvalidStateError:
        reservation = None
    replay = get_staged_draft_publication_replay(input.run_id)
    if replay.status == "finalized":
        metadata = _required_bundle_metadata(replay)
        commit_sha = replay.commit_sha
        pr_number = replay.pr_number
        pr_url = replay.pr_url
        if not commit_sha or not pr_number or not pr_url:
            raise RuntimeError("Finalized draft publication is missing authoritative references")
        return ExportDraftPublicationBundleOutput(
            publication_id=replay.publication_id,
            storage_path=metadata.storage_path,
            bundle_sha256=metadata.bundle_sha256,
            bundle_head_sha=metadata.bundle_head_sha,
            bundle_byte_count=metadata.bundle_byte_count,
            commit_sha=commit_sha,
            pr_number=pr_number,
            pr_url=pr_url,
        )
    if replay.status != "reserved":
        publication = _replay_activity_publication(input.run_id, replay.status)
        metadata = _required_bundle_metadata(replay)
        payload = object_storage.read_bytes(metadata.storage_path, missing_ok=True)
        if (
            not isinstance(payload, bytes)
            or len(payload) != metadata.bundle_byte_count
            or hashlib.sha256(payload).hexdigest() != metadata.bundle_sha256
        ):
            raise RuntimeError("Draft publication bundle replay verification failed")
        plan = _plan(publication, Path("/tmp/tasks-draft-publications/replay"))
        inspection = inspect_publication_bundle(payload, plan)
        if inspection.head_commit != metadata.bundle_head_sha:
            raise RuntimeError("Draft publication bundle replay head verification failed")
        base = _load_base(publication, inspection.changed_paths)
        validated = validate_publication_bundle(payload, plan, base)
        _scan(publication, validated)
        return _output(input.run_id, publication, replay, validated)
    if reservation is None:
        raise RuntimeError("Draft publication reservation is unavailable")
    publication = _activity_publication(input.run_id)
    if (
        reservation.publication_id != publication.publication_id
        or replay.publication_id != publication.publication_id
        or reservation.repository != publication.repository
        or reservation.base_sha != publication.base_sha
        or reservation.branch != publication.branch
    ):
        raise RuntimeError("Draft publication reservation changed during activity setup")
    sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    if not isinstance(sandbox, ModalSandbox):
        raise RuntimeError("Sandbox provider cannot export draft publication bundles")
    stopped = sandbox.stop_agent_server()
    if stopped.exit_code != 0:
        raise RuntimeError("Agent server did not stop before draft publication export")
    # Re-lock after stopping: the lease may have expired while the agent was running.
    publication = _activity_publication(input.run_id)
    directory = f"/tmp/tasks-draft-publications/{uuid4().hex}"
    script_path = f"{directory}/normalize.py"
    metadata_path = f"{directory}/result.json"
    plan = _plan(publication, Path(directory))
    try:
        created = sandbox.execute(
            f"install -d -m 700 -- {shlex.quote(directory)}", timeout_seconds=_SANDBOX_TIMEOUT_SECONDS
        )
        if created.exit_code != 0:
            raise RuntimeError("Unable to create trusted bundle export directory")
        written = sandbox.write_file(
            script_path,
            build_publication_bundle_script(plan, Path(script_path)).encode(),
            timeout_seconds=_SANDBOX_TIMEOUT_SECONDS,
        )
        if written.exit_code != 0:
            raise RuntimeError("Unable to write trusted bundle normalization script")
        executed = sandbox.execute(
            f"env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/python3 {shlex.quote(script_path)} > {shlex.quote(metadata_path)}",
            timeout_seconds=_SANDBOX_TIMEOUT_SECONDS,
        )
        if executed.exit_code != 0:
            raise RuntimeError("Unable to create normalized draft publication bundle")
        metadata = json.loads(sandbox.read_file_bytes(metadata_path, _MAX_METADATA_BYTES))
        bundle_path = _bundle_path_from_metadata(directory, metadata)
        payload = sandbox.read_file_bytes(bundle_path, _MAX_BUNDLE_BYTES)
        digest = hashlib.sha256(payload).hexdigest()
        inspection = inspect_publication_bundle(payload, plan)
        base = _load_base(publication, inspection.changed_paths)
        validated = validate_publication_bundle(payload, plan, base)
        _run_required_publication_gates(
            sandbox,
            input.run_id,
            publication,
            tuple(file.path for file in validated.files),
        )
        _scan(publication, validated)
        # Re-lock before starting object-store I/O; no external calls occur in the callback.
        _activity_publication(input.run_id)
        storage_path = f"tasks/draft-publications/{publication.publication_id}/{digest}.bundle"
        readback = object_storage.read_bytes(storage_path, missing_ok=True)
        if readback is None:
            object_storage.write(storage_path, payload, {"ContentType": "application/x-git-bundle"})
            readback = object_storage.read_bytes(storage_path, missing_ok=True)
        if (
            not isinstance(readback, bytes)
            or len(readback) != len(payload)
            or hashlib.sha256(readback).hexdigest() != digest
        ):
            raise RuntimeError("Draft publication bundle readback verification failed")
        validated = validate_publication_bundle(readback, plan, base)
        _scan(publication, validated)
        _activity_publication(input.run_id)
        record_staged_draft_publication_bundle(
            input.run_id,
            storage_path=storage_path,
            bundle_head_sha=inspection.head_commit,
            bundle_sha256=digest,
            bundle_byte_count=len(readback),
        )
        published = publish_staged_draft_publication(input.run_id, _proposal(validated))
        return ExportDraftPublicationBundleOutput(
            publication_id=publication.publication_id,
            storage_path=storage_path,
            bundle_sha256=digest,
            bundle_head_sha=inspection.head_commit,
            bundle_byte_count=len(readback),
            commit_sha=published.commit_sha,
            pr_number=published.pr_number,
            pr_url=published.pr_url,
        )
    finally:
        _cleanup(sandbox, directory)


@activity.defn
@asyncify
def export_draft_publication_bundle(input: ExportDraftPublicationBundleInput) -> ExportDraftPublicationBundleOutput:
    return export_draft_publication_bundle_now(input)
