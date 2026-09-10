"""Durable lifecycle operations for a protected draft pull request."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.tasks.backend.facade.draft_publication import (
    DraftPublicationLifecycleResult,
    DraftPublicationRequest,
    DraftPublicationResult,
    InvalidDraftPublicationError,
)
from products.tasks.backend.logic.services.publication_bundle import PublicationBundlePlan, validate_publication_bundle
from products.tasks.backend.logic.services.publication_policy import (
    PublicationPolicyError,
    validate_bundle_acceptance_authority,
    validate_publication_authority,
)
from products.tasks.backend.logic.services.publication_transport import (
    PublicationAmbiguousError,
    PublicationConflictError,
    PublicationRejectedError,
    PublicationTransportError,
    PublicationTransportInput,
    ServerGitHubPublicationClient,
    create_draft_pull_request,
    create_server_branch,
    create_server_commit,
    read_draft_pull_request_state,
    reconcile_draft_pull_request,
    reconcile_server_branch,
)
from products.tasks.backend.models import TaskDraftPublication, TaskStagedRun

_MAX_LOGICAL_ARTIFACT_KEY_LENGTH = 255
_MAX_COMMIT_MESSAGE_LENGTH = 500
_MAX_PR_TITLE_LENGTH = 256
_MAX_PR_BODY_LENGTH = 20_000
_COMMIT_AUTHOR_NAME = "PostHog Tasks"
_COMMIT_AUTHOR_EMAIL = "tasks@posthog.com"
_MAX_RECONCILIATION_ATTEMPTS = 3


@frozen
class ValidatedBundleRecord:
    storage_ref: str
    sha256: str
    byte_count: int
    artifact_head_sha: str
    base_tree_sha: str
    head_tree_sha: str
    gate_summary_ref: str


def _get_github_token(integration_id: int) -> str | None:
    from products.tasks.backend.temporal.process_task.utils import get_github_token

    return get_github_token(integration_id)


def _result(publication: TaskDraftPublication) -> DraftPublicationResult:
    return DraftPublicationResult(
        publication_id=publication.id,
        status=cast(Literal["pending", "published", "unknown", "blocked", "revoked"], publication.status),
        pr_number=publication.pr_number,
        pr_url=publication.pr_url,
    )


def _validate_request(input: DraftPublicationRequest) -> None:
    fields = (
        (input.logical_artifact_key, _MAX_LOGICAL_ARTIFACT_KEY_LENGTH),
        (input.commit_message, _MAX_COMMIT_MESSAGE_LENGTH),
        (input.pr_title, _MAX_PR_TITLE_LENGTH),
        (input.pr_body, _MAX_PR_BODY_LENGTH),
    )
    if any(not value.strip() or len(value) > maximum for value, maximum in fields[:3]):
        raise InvalidDraftPublicationError("Draft publication metadata is invalid")
    if len(input.pr_body) > _MAX_PR_BODY_LENGTH or input.starts_before >= input.expires_at:
        raise InvalidDraftPublicationError("Draft publication window is invalid")


def _normalize_request(input: DraftPublicationRequest) -> DraftPublicationRequest:
    return replace(
        input,
        logical_artifact_key=input.logical_artifact_key.strip(),
        commit_message=input.commit_message.strip(),
        pr_title=input.pr_title.strip(),
        pr_body=input.pr_body.strip(),
    )


def _same_request(publication: TaskDraftPublication, input: DraftPublicationRequest) -> bool:
    return (
        publication.caller_id == input.caller_id
        and publication.logical_artifact_key == input.logical_artifact_key
        and publication.commit_message == input.commit_message
        and publication.pr_title == input.pr_title
        and publication.pr_body == input.pr_body
        and publication.starts_before == input.starts_before
        and publication.expires_at == input.expires_at
    )


def reserve_publication(input: DraftPublicationRequest) -> DraftPublicationResult:
    input = _normalize_request(input)
    _validate_request(input)
    if input.expires_at <= timezone.now():
        raise InvalidDraftPublicationError("Draft publication reservation has expired")
    try:
        with transaction.atomic():
            staged_run = (
                TaskStagedRun.objects.for_team(input.team_id)
                .select_for_update(of=("self",))
                .select_related("execution_run")
                .get(id=input.staged_run_id, caller_id=input.caller_id)
            )
            if (
                staged_run.execution_run is None
                or staged_run.execution_run.status
                not in {
                    staged_run.execution_run.Status.QUEUED,
                    staged_run.execution_run.Status.IN_PROGRESS,
                }
                or staged_run.cancelled_at is not None
                or staged_run.capabilities_revoked_at is not None
                or not all(
                    (
                        staged_run.repository,
                        staged_run.base_sha,
                        staged_run.base_branch,
                        staged_run.github_integration_id,
                        staged_run.github_installation_id,
                    )
                )
            ):
                raise InvalidDraftPublicationError("Staged execution is not eligible for draft publication")
            existing = getattr(staged_run, "draft_publication", None)
            if existing is not None:
                if not _same_request(existing, input):
                    raise InvalidDraftPublicationError("Draft publication replay does not match the reservation")
                return _result(existing)
            publication = TaskDraftPublication.objects.for_team(input.team_id).create(
                team_id=input.team_id,
                caller_id=input.caller_id,
                staged_run=staged_run,
                logical_artifact_key=input.logical_artifact_key,
                repository=cast(str, staged_run.repository),
                base_sha=cast(str, staged_run.base_sha),
                base_branch=cast(str, staged_run.base_branch),
                github_integration_id=cast(int, staged_run.github_integration_id),
                github_installation_id=cast(str, staged_run.github_installation_id),
                head_branch=f"codex/tasks-draft-{uuid4().hex}",
                commit_message=input.commit_message,
                pr_title=input.pr_title,
                pr_body=input.pr_body,
                starts_before=input.starts_before,
                expires_at=input.expires_at,
            )
            return _result(publication)
    except TaskStagedRun.DoesNotExist as err:
        raise InvalidDraftPublicationError("Staged execution is not bound to this team and caller") from err
    except IntegrityError as err:
        raise InvalidDraftPublicationError("Draft publication reservation conflicts with an existing claim") from err


def get_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> DraftPublicationResult:
    try:
        publication = TaskDraftPublication.objects.for_team(team_id).get(id=publication_id, caller_id=caller_id)
    except TaskDraftPublication.DoesNotExist as err:
        raise InvalidDraftPublicationError("Draft publication is not bound to this team and caller") from err
    return _result(publication)


def get_publication_lifecycle(
    *, team_id: int, caller_id: UUID, publication_id: UUID
) -> DraftPublicationLifecycleResult:
    """Read a publication without mutating its local lifecycle or GitHub resource."""
    try:
        publication = TaskDraftPublication.objects.for_team(team_id).get(id=publication_id, caller_id=caller_id)
    except TaskDraftPublication.DoesNotExist as err:
        raise InvalidDraftPublicationError("Draft publication is not bound to this team and caller") from err

    local_status = cast(Literal["pending", "published", "unknown", "blocked", "revoked"], publication.status)
    if local_status == "pending":
        return DraftPublicationLifecycleResult(
            publication_id=publication.id,
            local_status=local_status,
            remote_state="pending",
            pr_number=publication.pr_number,
            pr_url=publication.pr_url,
        )
    if local_status != "published":
        return DraftPublicationLifecycleResult(
            publication_id=publication.id,
            local_status=local_status,
            remote_state="unknown",
            pr_number=publication.pr_number,
            pr_url=publication.pr_url,
        )
    if (
        publication.pr_number is None
        or publication.pr_url is None
        or publication.github_commit_sha is None
        or not publication.repository
        or not publication.base_branch
        or not publication.head_branch
    ):
        return _unknown_lifecycle(publication, local_status)
    try:
        token = _get_github_token(publication.github_integration_id)
        if not token:
            return _unknown_lifecycle(publication, local_status)
        transport_input = PublicationTransportInput(
            repository=publication.repository,
            base_sha=publication.base_sha,
            base_branch=publication.base_branch,
            head_branch=publication.head_branch,
            commit_message=publication.commit_message,
            commit_author_name=_COMMIT_AUTHOR_NAME,
            commit_author_email=_COMMIT_AUTHOR_EMAIL,
            commit_timestamp=int(publication.created_at.timestamp()),
            expected_base_tree_sha=publication.base_sha,
            expected_head_tree_sha=publication.base_sha,
            operations=(),
            title=publication.pr_title,
            body=publication.pr_body,
        )
        remote_state = read_draft_pull_request_state(
            ServerGitHubPublicationClient(installation_id=publication.github_installation_id, token=token),
            transport_input,
            pr_number=publication.pr_number,
            expected_pr_url=publication.pr_url,
            expected_commit_sha=publication.github_commit_sha,
        )
    except Exception:
        return _unknown_lifecycle(publication, local_status)
    return DraftPublicationLifecycleResult(
        publication_id=publication.id,
        local_status=local_status,
        remote_state=remote_state,
        pr_number=publication.pr_number,
        pr_url=publication.pr_url,
    )


def _unknown_lifecycle(
    publication: TaskDraftPublication, local_status: Literal["published"]
) -> DraftPublicationLifecycleResult:
    return DraftPublicationLifecycleResult(
        publication_id=publication.id,
        local_status=local_status,
        remote_state="unknown",
        pr_number=publication.pr_number,
        pr_url=publication.pr_url,
    )


def revoke_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> bool:
    with transaction.atomic():
        try:
            publication = (
                TaskDraftPublication.objects.for_team(team_id)
                .select_for_update(of=("self",))
                .get(id=publication_id, caller_id=caller_id)
            )
        except TaskDraftPublication.DoesNotExist:
            return False
        if publication.status in {TaskDraftPublication.Status.PUBLISHED, TaskDraftPublication.Status.REVOKED}:
            return False
        publication.status = TaskDraftPublication.Status.REVOKED
        publication.revoked_at = timezone.now()
        publication.save(update_fields=["status", "revoked_at", "updated_at"])
        return True


def record_validated_bundle(
    *, team_id: int, caller_id: UUID, publication_id: UUID, bundle: ValidatedBundleRecord
) -> None:
    policy_error: PublicationPolicyError | None = None
    with transaction.atomic():
        try:
            publication = (
                TaskDraftPublication.objects.for_team(team_id)
                .select_for_update(of=("self",))
                .select_related("staged_run__task__created_by", "staged_run__task__team", "staged_run__execution_run")
                .get(id=publication_id, caller_id=caller_id)
            )
        except TaskDraftPublication.DoesNotExist as err:
            raise InvalidDraftPublicationError("Draft publication is not bound to this team and caller") from err
        try:
            validate_bundle_acceptance_authority(publication)
        except PublicationPolicyError as err:
            block_publication(publication)
            policy_error = err
        if policy_error is None:
            existing = (
                publication.bundle_storage_ref,
                publication.bundle_sha256,
                publication.bundle_size,
                publication.bundle_head_sha,
                publication.bundle_base_tree_sha,
                publication.bundle_head_tree_sha,
                publication.gate_summary_ref,
            )
            expected = (
                bundle.storage_ref,
                bundle.sha256,
                bundle.byte_count,
                bundle.artifact_head_sha,
                bundle.base_tree_sha,
                bundle.head_tree_sha,
                bundle.gate_summary_ref,
            )
            if any(value is not None for value in existing):
                if existing != expected:
                    raise InvalidDraftPublicationError("Draft publication bundle replay does not match")
                return
            publication.bundle_storage_ref = bundle.storage_ref
            publication.bundle_sha256 = bundle.sha256
            publication.bundle_size = bundle.byte_count
            publication.bundle_head_sha = bundle.artifact_head_sha
            publication.bundle_base_tree_sha = bundle.base_tree_sha
            publication.bundle_head_tree_sha = bundle.head_tree_sha
            publication.gate_summary_ref = bundle.gate_summary_ref
            publication.gate_summary = {"git_diff_check": "passed"}
            publication.save(
                update_fields=[
                    "bundle_storage_ref",
                    "bundle_sha256",
                    "bundle_size",
                    "bundle_head_sha",
                    "bundle_base_tree_sha",
                    "bundle_head_tree_sha",
                    "gate_summary_ref",
                    "gate_summary",
                    "updated_at",
                ]
            )
    if policy_error is not None:
        raise InvalidDraftPublicationError(str(policy_error)) from policy_error


def block_publication(publication: TaskDraftPublication) -> bool:
    updated = (
        TaskDraftPublication.objects.for_team(publication.team_id)
        .filter(
            id=publication.id,
            caller_id=publication.caller_id,
            status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
            revoked_at__isnull=True,
        )
        .update(status=TaskDraftPublication.Status.BLOCKED, blocked_at=timezone.now(), updated_at=timezone.now())
    )
    return updated == 1


def _mark_unknown(publication: TaskDraftPublication, kind: str) -> None:
    TaskDraftPublication.objects.for_team(publication.team_id).filter(
        id=publication.id,
        status=TaskDraftPublication.Status.PENDING,
        revoked_at__isnull=True,
    ).update(status=TaskDraftPublication.Status.UNKNOWN, unknown_at=timezone.now(), ambiguity_kind=kind)


def _validated_transport_input(publication: TaskDraftPublication) -> PublicationTransportInput:
    storage_ref = publication.bundle_storage_ref
    if not storage_ref:
        raise InvalidDraftPublicationError("Draft publication bundle is unavailable")
    payload = object_storage.read_bytes(storage_ref, missing_ok=True)
    if (
        not isinstance(payload, bytes)
        or len(payload) != publication.bundle_size
        or hashlib.sha256(payload).hexdigest() != publication.bundle_sha256
    ):
        raise InvalidDraftPublicationError("Draft publication bundle readback failed")
    plan = PublicationBundlePlan(
        workspace_path=Path("/nonexistent-publication-workspace"),
        export_root=Path("/nonexistent-publication-export"),
        repository=publication.repository,
        base_commit=publication.base_sha,
        commit_message=publication.commit_message,
        commit_timestamp=int(publication.created_at.timestamp()),
    )
    validated = validate_publication_bundle(payload, plan)
    if (
        validated.artifact_head_sha != publication.bundle_head_sha
        or validated.base_tree_sha != publication.bundle_base_tree_sha
        or validated.head_tree_sha != publication.bundle_head_tree_sha
    ):
        raise InvalidDraftPublicationError("Draft publication bundle identity changed after acceptance")
    return PublicationTransportInput(
        repository=publication.repository,
        base_sha=publication.base_sha,
        base_branch=publication.base_branch,
        head_branch=publication.head_branch,
        commit_message=publication.commit_message,
        commit_author_name=_COMMIT_AUTHOR_NAME,
        commit_author_email=_COMMIT_AUTHOR_EMAIL,
        commit_timestamp=int(publication.created_at.timestamp()),
        expected_base_tree_sha=validated.base_tree_sha,
        expected_head_tree_sha=validated.head_tree_sha,
        operations=validated.operations,
        title=publication.pr_title,
        body=publication.pr_body,
    )


def _publication_for_write(*, team_id: int, caller_id: UUID, publication_id: UUID) -> TaskDraftPublication:
    try:
        return (
            TaskDraftPublication.objects.for_team(team_id)
            .select_related("staged_run__task__created_by", "staged_run__task__team", "staged_run__execution_run")
            .get(id=publication_id, caller_id=caller_id)
        )
    except TaskDraftPublication.DoesNotExist as err:
        raise InvalidDraftPublicationError("Draft publication is not bound to this team and caller") from err


def publish_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> DraftPublicationResult:
    publication = _publication_for_write(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
    if publication.status in {
        TaskDraftPublication.Status.PUBLISHED,
        TaskDraftPublication.Status.BLOCKED,
        TaskDraftPublication.Status.REVOKED,
    }:
        return _result(publication)
    try:
        validate_publication_authority(publication)
        transport_input = _validated_transport_input(publication)
    except (PublicationPolicyError, InvalidDraftPublicationError) as err:
        block_publication(publication)
        raise InvalidDraftPublicationError(str(err)) from err

    credential_error: Exception | None = None
    try:
        token = _get_github_token(publication.github_integration_id)
    except Exception as err:
        token = None
        credential_error = err
    if not token:
        block_publication(publication)
        raise InvalidDraftPublicationError("GitHub integration credential is unavailable") from credential_error
    client = ServerGitHubPublicationClient(installation_id=publication.github_installation_id, token=token)

    if publication.status == TaskDraftPublication.Status.UNKNOWN:
        if publication.reconciliation_attempts >= _MAX_RECONCILIATION_ATTEMPTS:
            return _result(publication)
        updated = (
            TaskDraftPublication.objects.for_team(team_id)
            .filter(id=publication.id, status=TaskDraftPublication.Status.UNKNOWN, revoked_at__isnull=True)
            .update(reconciliation_attempts=publication.reconciliation_attempts + 1)
        )
        if updated != 1:
            return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
    if publication.claimed_at is None:
        claim_now = timezone.now()
        claimed = (
            TaskDraftPublication.objects.for_team(team_id)
            .filter(
                id=publication.id,
                status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
                claimed_at__isnull=True,
                revoked_at__isnull=True,
                starts_before__gt=claim_now,
            )
            .update(claimed_at=claim_now, updated_at=claim_now)
        )
        if claimed != 1:
            TaskDraftPublication.objects.for_team(team_id).filter(
                id=publication.id,
                status=TaskDraftPublication.Status.PENDING,
                claimed_at__isnull=True,
                revoked_at__isnull=True,
                starts_before__lte=claim_now,
            ).update(
                status=TaskDraftPublication.Status.BLOCKED,
                blocked_at=claim_now,
                updated_at=claim_now,
            )
            return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
    try:
        commit_sha = publication.github_commit_sha
        if commit_sha is None:
            commit_sha = create_server_commit(client, transport_input)
            updated = (
                TaskDraftPublication.objects.for_team(team_id)
                .filter(
                    id=publication.id,
                    status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
                    revoked_at__isnull=True,
                )
                .update(
                    status=TaskDraftPublication.Status.PENDING,
                    github_commit_sha=commit_sha,
                    ambiguity_kind="branch",
                )
            )
            if updated != 1:
                return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
        if publication.branch_created_at is None:
            branch = reconcile_server_branch(client, transport_input, expected_branch_sha=commit_sha)
            if branch is None:
                updated = (
                    TaskDraftPublication.objects.for_team(team_id)
                    .filter(
                        id=publication.id,
                        status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
                        revoked_at__isnull=True,
                    )
                    .update(ambiguity_kind="branch")
                )
                if updated != 1:
                    return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
                create_server_branch(client, transport_input, commit_sha)
            updated = (
                TaskDraftPublication.objects.for_team(team_id)
                .filter(
                    id=publication.id,
                    status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
                    revoked_at__isnull=True,
                )
                .update(
                    status=TaskDraftPublication.Status.PENDING,
                    branch_created_at=timezone.now(),
                    ambiguity_kind="pr",
                    pr_creating_at=timezone.now(),
                    reconciled_at=timezone.now(),
                )
            )
            if updated != 1:
                return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
        pull_request = reconcile_draft_pull_request(client, transport_input, expected_branch_sha=commit_sha)
        if pull_request is None:
            updated = (
                TaskDraftPublication.objects.for_team(team_id)
                .filter(
                    id=publication.id,
                    status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
                    revoked_at__isnull=True,
                )
                .update(ambiguity_kind="pr", pr_creating_at=timezone.now())
            )
            if updated != 1:
                return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
            pull_request = create_draft_pull_request(client, transport_input, commit_sha)
    except PublicationAmbiguousError:
        current = _publication_for_write(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
        _mark_unknown(current, current.ambiguity_kind or "commit")
        return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
    except (PublicationConflictError, PublicationRejectedError, ValueError) as err:
        block_publication(publication)
        raise InvalidDraftPublicationError(str(err)) from err
    except PublicationTransportError:
        return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
    TaskDraftPublication.objects.for_team(team_id).filter(
        id=publication.id,
        status__in=[TaskDraftPublication.Status.PENDING, TaskDraftPublication.Status.UNKNOWN],
        revoked_at__isnull=True,
    ).update(
        status=TaskDraftPublication.Status.PUBLISHED,
        pr_number=pull_request.number,
        pr_url=pull_request.url,
        published_at=timezone.now(),
        ambiguity_kind=None,
    )
    return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
