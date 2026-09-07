"""Trusted post-run bundle export and publication activity."""

from __future__ import annotations

import json
import shlex
import hashlib
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.tasks.backend.facade.draft_publication import DraftPublicationResult
from products.tasks.backend.logic.services.publication_bundle import (
    PublicationBundleError,
    PublicationBundleLimits,
    PublicationBundlePlan,
    build_publication_bundle_script,
    validate_publication_bundle,
)
from products.tasks.backend.logic.services.publication_service import (
    ValidatedBundleRecord,
    block_publication,
    publish_publication,
    record_validated_bundle,
)
from products.tasks.backend.logic.services.sandbox import (
    SandboxBase,
    get_sandbox_class_for_sandbox_id,
    sandbox_repo_path,
)
from products.tasks.backend.models import TaskDraftPublication, TaskRun, TaskStagedRun

_EXPORT_ROOT = "/tmp/tasks-draft-publications"
_MAX_METADATA_BYTES = 4096
_MAX_GATE_BYTES = 1024 * 1024


@frozen
class PublishTaskArtifactInput:
    staged_run_id: UUID
    publication_id: UUID


def _publication(input: PublishTaskArtifactInput) -> TaskDraftPublication:
    try:
        publication = (
            TaskDraftPublication.objects.unscoped()
            .select_related("staged_run__execution_run")
            .get(id=input.publication_id, staged_run_id=input.staged_run_id)
        )
    except TaskDraftPublication.DoesNotExist as err:
        raise ApplicationError("Draft publication binding is unavailable", non_retryable=True) from err
    execution = publication.staged_run.execution_run
    if execution is None or execution.status != TaskRun.Status.COMPLETED:
        raise ApplicationError("Staged execution has not completed", non_retryable=True)
    return publication


def _sandbox_id(publication: TaskDraftPublication) -> str:
    execution = publication.staged_run.execution_run
    value = (execution.state or {}).get("sandbox_id") if execution is not None else None
    if not isinstance(value, str) or not value:
        raise ApplicationError("Completed staged execution has no authoritative sandbox", non_retryable=True)
    return value


def _block_and_fail(publication: TaskDraftPublication, message: str, error: Exception | None = None) -> NoReturn:
    block_publication(publication)
    if error is not None:
        raise ApplicationError(message, non_retryable=True) from error
    raise ApplicationError(message, non_retryable=True)


def _read_normalized_output(
    publication: TaskDraftPublication, sandbox: SandboxBase, path: str, max_bytes: int
) -> bytes:
    try:
        return sandbox.read_file_bytes(path, max_bytes)
    except ValueError as err:
        _block_and_fail(publication, "Publication output exceeded its trusted bounds", err)


@activity.defn
def resolve_completed_publication(run_id: str) -> PublishTaskArtifactInput | None:
    try:
        execution_run_id = UUID(run_id)
    except ValueError:
        return None
    with transaction.atomic():
        staged_run = (
            TaskStagedRun.objects.unscoped()
            .select_for_update(of=("self",))
            .select_related("draft_publication", "execution_run")
            .filter(execution_run_id=execution_run_id, execution_run__status=TaskRun.Status.COMPLETED)
            .first()
        )
        publication = getattr(staged_run, "draft_publication", None) if staged_run is not None else None
        if publication is None or publication.status not in {
            TaskDraftPublication.Status.PENDING,
            TaskDraftPublication.Status.UNKNOWN,
        }:
            return None
        return PublishTaskArtifactInput(staged_run_id=publication.staged_run_id, publication_id=publication.id)


@activity.defn
def finalize_failed_publication(input: PublishTaskArtifactInput) -> None:
    now = timezone.now()
    (
        TaskDraftPublication.objects.unscoped()
        .filter(
            id=input.publication_id,
            staged_run_id=input.staged_run_id,
            status=TaskDraftPublication.Status.PENDING,
            revoked_at__isnull=True,
        )
        .filter(Q(bundle_storage_ref__isnull=True) | Q(bundle_storage_ref=""))
        .update(status=TaskDraftPublication.Status.BLOCKED, blocked_at=now, updated_at=now)
    )


def _export_and_store(publication: TaskDraftPublication) -> None:
    sandbox_id = _sandbox_id(publication)
    sandbox = get_sandbox_class_for_sandbox_id(sandbox_id).get_by_id(sandbox_id)
    stopped = sandbox.stop_agent_server()
    if stopped.exit_code != 0:
        raise ApplicationError("Agent server did not stop before publication export")
    directory = f"{_EXPORT_ROOT}/{publication.id}-{uuid4().hex}"
    script_path = f"{directory}/normalize.py"
    metadata_path = f"{directory}/metadata.json"
    gate_path = f"{directory}/git-diff-check.log"
    workspace = sandbox_repo_path(publication.repository)
    plan = PublicationBundlePlan(
        workspace_path=Path(workspace),
        export_root=Path(directory),
        repository=publication.repository,
        base_commit=publication.base_sha,
        commit_message=publication.commit_message,
        commit_timestamp=int(publication.created_at.timestamp()),
    )
    try:
        created = sandbox.execute(f"install -d -m 700 -- {shlex.quote(directory)}", timeout_seconds=60)
        if created.exit_code != 0:
            raise ApplicationError("Unable to create trusted publication export directory")
        written = sandbox.write_file(script_path, build_publication_bundle_script(plan).encode(), timeout_seconds=60)
        if written.exit_code != 0:
            raise ApplicationError("Unable to install trusted publication normalizer")
        normalized = sandbox.execute(
            f"env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/python3 {shlex.quote(script_path)} > {shlex.quote(metadata_path)}",
            timeout_seconds=60,
        )
        if normalized.exit_code != 0:
            _block_and_fail(publication, "Trusted publication normalization failed")
        try:
            metadata = json.loads(_read_normalized_output(publication, sandbox, metadata_path, _MAX_METADATA_BYTES))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            _block_and_fail(publication, "Trusted publication normalization failed", err)
        bundle_path = metadata.get("bundle_path") if isinstance(metadata, dict) else None
        expected_root = Path(directory)
        candidate = Path(bundle_path) if isinstance(bundle_path, str) else Path()
        if (
            not candidate.is_absolute()
            or candidate.name != "publication.bundle"
            or candidate.parent.parent != expected_root
        ):
            _block_and_fail(publication, "Publication normalizer returned an unsafe bundle path")
        limits = PublicationBundleLimits()
        bundle = _read_normalized_output(publication, sandbox, str(candidate), limits.max_bundle_bytes)
        try:
            validated = validate_publication_bundle(bundle, plan)
        except PublicationBundleError as err:
            _block_and_fail(publication, "Publication bundle validation failed", err)
        gate = sandbox.execute(
            " ".join(
                [
                    "env -i PATH=/usr/bin:/bin HOME=/nonexistent",
                    "/usr/bin/git --no-optional-locks -c diff.external= -c core.pager=cat",
                    f"-C {shlex.quote(workspace)} diff --check {shlex.quote(publication.base_sha)} --",
                    f"> {shlex.quote(gate_path)} 2>&1",
                ]
            ),
            timeout_seconds=8 * 60,
        )
        gate_output = _read_normalized_output(publication, sandbox, gate_path, _MAX_GATE_BYTES)
        bundle_ref = f"tasks/draft-publications/{publication.id}/publication.bundle"
        gate_ref = f"tasks/draft-publications/{publication.id}/git-diff-check.log"
        object_storage.write(bundle_ref, bundle, {"ContentType": "application/octet-stream"})
        object_storage.write(gate_ref, gate_output, {"ContentType": "text/plain"})
        readback = object_storage.read_bytes(bundle_ref, missing_ok=True)
        digest = hashlib.sha256(bundle).hexdigest()
        if readback != bundle or hashlib.sha256(readback or b"").hexdigest() != digest:
            raise ApplicationError("Publication bundle object-storage readback failed")
        if gate.exit_code != 0:
            _block_and_fail(publication, "Protected publication gate failed")
        record_validated_bundle(
            team_id=publication.team_id,
            caller_id=publication.caller_id,
            publication_id=publication.id,
            bundle=ValidatedBundleRecord(
                storage_ref=bundle_ref,
                sha256=digest,
                byte_count=len(bundle),
                artifact_head_sha=validated.artifact_head_sha,
                base_tree_sha=validated.base_tree_sha,
                head_tree_sha=validated.head_tree_sha,
                gate_summary_ref=gate_ref,
            ),
        )
    finally:
        try:
            sandbox.execute(f"rm -rf -- {shlex.quote(directory)}", timeout_seconds=60)
        except Exception:
            pass


@activity.defn
def publish_task_artifact(input: PublishTaskArtifactInput) -> DraftPublicationResult:
    publication = _publication(input)
    if publication.bundle_storage_ref is None:
        _export_and_store(publication)
    result = publish_publication(
        team_id=publication.team_id,
        caller_id=publication.caller_id,
        publication_id=publication.id,
    )
    if result.status in {TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN}:
        raise ApplicationError("Draft publication outcome is not terminal")
    return result
