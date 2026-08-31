"""Durable, brokered publication of one Tasks-owned draft pull request."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen
from posthog.models import Integration
from posthog.models.integration import GitHubIntegration

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.logic.services.publication_gate_ledger import require_successful_publication_gates
from products.tasks.backend.logic.services.publication_transport import (
    BranchCreation,
    DraftPublicationInput,
    DraftPullRequest,
    GitHubPublicationClient,
    NormalizedTreeOperation,
    create_draft_pull_request,
    create_server_branch,
    create_server_commit,
    reconcile_draft_pull_request,
    reconcile_server_branch,
)
from products.tasks.backend.logic.services.staged_task_runs import (
    StagedPublicationValidationMode,
    with_validated_staged_draft_publication,
)
from products.tasks.backend.models import TaskDraftPublication, TaskPublicationLease


class PublicationServiceError(RuntimeError):
    """A durable draft-publication claim cannot safely advance."""


class PublicationTransport(Protocol):
    def create_commit(self, client: GitHubPublicationClient, publication: DraftPublicationInput) -> str: ...

    def create_branch(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
    ) -> BranchCreation: ...

    def create_pull_request(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
    ) -> DraftPullRequest: ...

    def reconcile(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, *, expected_branch_sha: str
    ) -> DraftPullRequest | None: ...

    def reconcile_branch(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, *, expected_branch_sha: str
    ) -> BranchCreation | None: ...


@frozen
class PublicationProposal:
    operations: tuple[NormalizedTreeOperation, ...]


@frozen
class PublishedDraftPublication:
    commit_sha: str
    pr_number: int
    pr_url: str


@frozen
class StagedDraftPublicationReplay:
    """Validated persisted state for activity replay; bundle bytes never cross this boundary."""

    publication_id: str
    status: str
    bundle_storage_path: str | None
    bundle_head_sha: str | None
    bundle_sha256: str | None
    bundle_byte_count: int | None
    commit_sha: str | None
    pr_number: int | None
    pr_url: str | None


@frozen
class _TransportAdapter:
    def create_commit(self, client: GitHubPublicationClient, publication: DraftPublicationInput) -> str:
        return create_server_commit(client, publication)

    def create_branch(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
    ) -> BranchCreation:
        return create_server_branch(client, publication, commit_sha)

    def create_pull_request(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
    ) -> DraftPullRequest:
        return create_draft_pull_request(client, publication, commit_sha)

    def reconcile(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, *, expected_branch_sha: str
    ) -> DraftPullRequest | None:
        return reconcile_draft_pull_request(client, publication, expected_branch_sha=expected_branch_sha)

    def reconcile_branch(
        self, client: GitHubPublicationClient, publication: DraftPublicationInput, *, expected_branch_sha: str
    ) -> BranchCreation | None:
        return reconcile_server_branch(client, publication, expected_branch_sha=expected_branch_sha)


_TRANSPORT = _TransportAdapter()


def get_staged_draft_publication_replay(run_id: str) -> StagedDraftPublicationReplay:
    """Read a fully locked publication claim for replay without loading its bundle bytes."""

    def operation(
        _integration: Integration,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        _lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> StagedDraftPublicationReplay:
        return StagedDraftPublicationReplay(
            publication_id=str(publication.id),
            status=publication.status,
            bundle_storage_path=publication.bundle_storage_path,
            bundle_head_sha=publication.bundle_head_sha,
            bundle_sha256=publication.bundle_sha256,
            bundle_byte_count=publication.bundle_byte_count,
            commit_sha=publication.github_commit_sha,
            pr_number=publication.pr_number,
            pr_url=publication.pr_url,
        )

    try:
        return with_validated_staged_draft_publication(run_id, operation, mode="reconcile_after_expiry")
    except TaskInvalidStateError:
        return with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")


def publish_staged_draft_publication(
    run_id: str,
    proposal: PublicationProposal,
    *,
    transport: PublicationTransport = _TRANSPORT,
    client_factory: Callable[[Integration], GitHubPublicationClient] | None = None,
    gate_validator: Callable[[str], None] | None = None,
) -> PublishedDraftPublication:
    """Advance one persisted claim without allowing sandbox-controlled publication authority."""
    (gate_validator or require_successful_publication_gates)(run_id)
    factory = client_factory or _github_client
    snapshot = _snapshot_for_publication(run_id, proposal)
    if snapshot.status == TaskDraftPublication.Status.FINALIZED:
        return _published(snapshot)
    if snapshot.status == TaskDraftPublication.Status.PUBLISHED:
        return _finalize(run_id, proposal, mode="reconcile_after_expiry")
    client = factory(snapshot.integration)
    if snapshot.status == TaskDraftPublication.Status.UPLOADED:
        return _create_commit_then_branch(run_id, proposal, snapshot, client, transport)
    if snapshot.status == TaskDraftPublication.Status.COMMIT_CREATED:
        return _create_branch_then_pull_request(run_id, proposal, snapshot, client, transport)
    if snapshot.status == TaskDraftPublication.Status.BRANCH_CREATING:
        return _reconcile_branch_then_pull_request(run_id, proposal, snapshot, client, transport)
    if snapshot.status == TaskDraftPublication.Status.BRANCH_CREATED:
        return _create_pull_request(run_id, proposal, snapshot, client, transport)
    if snapshot.status in {
        TaskDraftPublication.Status.PR_CREATING,
        TaskDraftPublication.Status.PUBLICATION_UNKNOWN,
    }:
        return _reconcile_pull_request(run_id, proposal, snapshot, client, transport)
    raise PublicationServiceError("publication claim is not in a resumable state")


def _snapshot_for_publication(run_id: str, proposal: PublicationProposal) -> _PublicationSnapshot:
    """Read retained external attempts after expiry, otherwise require the initial start window."""
    try:
        snapshot = _snapshot(run_id, proposal, mode="reconcile_after_expiry")
    except TaskInvalidStateError:
        snapshot = _snapshot(run_id, proposal, mode="in_flight_mutation")
    if snapshot.status == TaskDraftPublication.Status.UPLOADED:
        return _snapshot(run_id, proposal, mode="start_mutation")
    return snapshot


def _create_commit_then_branch(
    run_id: str,
    proposal: PublicationProposal,
    snapshot: _PublicationSnapshot,
    client: GitHubPublicationClient,
    transport: PublicationTransport,
) -> PublishedDraftPublication:
    # Git objects are content-addressed and unreachable until the later server ref POST.
    _revalidate_publication_authority(
        run_id,
        proposal,
        expected_status=TaskDraftPublication.Status.UPLOADED,
    )
    commit_sha = transport.create_commit(client, snapshot.input)
    _record_commit(run_id, proposal, commit_sha)
    return _create_branch_then_pull_request(
        run_id,
        proposal,
        _snapshot(run_id, proposal, mode="in_flight_mutation"),
        client,
        transport,
    )


def _create_branch_then_pull_request(
    run_id: str,
    proposal: PublicationProposal,
    snapshot: _PublicationSnapshot,
    client: GitHubPublicationClient,
    transport: PublicationTransport,
) -> PublishedDraftPublication:
    if snapshot.commit_sha is None:
        raise PublicationServiceError("publication claim has no server commit")
    _begin_branch_creation(run_id, proposal)
    try:
        _revalidate_publication_authority(
            run_id,
            proposal,
            expected_status=TaskDraftPublication.Status.BRANCH_CREATING,
        )
        transport.create_branch(client, snapshot.input, snapshot.commit_sha)
    except Exception as error:
        _mark_unknown(run_id, proposal, expected_status=TaskDraftPublication.Status.BRANCH_CREATING)
        raise PublicationServiceError("server branch outcome is unknown") from error
    _record_branch_creation(run_id, proposal, mode="reconcile_after_expiry")
    return _create_pull_request(
        run_id,
        proposal,
        _snapshot(run_id, proposal, mode="reconcile_after_expiry"),
        client,
        transport,
    )


def _reconcile_branch_then_pull_request(
    run_id: str,
    proposal: PublicationProposal,
    snapshot: _PublicationSnapshot,
    client: GitHubPublicationClient,
    transport: PublicationTransport,
) -> PublishedDraftPublication:
    if snapshot.commit_sha is None:
        raise PublicationServiceError("branch attempt has no server commit")
    branch = transport.reconcile_branch(client, snapshot.input, expected_branch_sha=snapshot.commit_sha)
    if branch is None:
        raise PublicationServiceError("server branch attempt has no exact branch")
    _record_branch_creation(run_id, proposal, mode="reconcile_after_expiry")
    return _create_pull_request(
        run_id,
        proposal,
        _snapshot(run_id, proposal, mode="reconcile_after_expiry"),
        client,
        transport,
    )


def _create_pull_request(
    run_id: str,
    proposal: PublicationProposal,
    snapshot: _PublicationSnapshot,
    client: GitHubPublicationClient,
    transport: PublicationTransport,
) -> PublishedDraftPublication:
    if snapshot.commit_sha is None:
        raise PublicationServiceError("pull request attempt has no server commit")
    _begin_pr_creation(run_id, proposal)
    try:
        _revalidate_publication_authority(
            run_id,
            proposal,
            expected_status=TaskDraftPublication.Status.PR_CREATING,
        )
        pull_request = transport.create_pull_request(client, snapshot.input, snapshot.commit_sha)
    except Exception as error:
        _mark_unknown(run_id, proposal, expected_status=TaskDraftPublication.Status.PR_CREATING)
        raise PublicationServiceError("draft pull request outcome is unknown") from error
    _record_published(run_id, proposal, pull_request, mode="reconcile_after_expiry")
    return _finalize(run_id, proposal, mode="reconcile_after_expiry")


@frozen
class _PublicationSnapshot:
    integration: Integration
    input: DraftPublicationInput
    status: str
    commit_sha: str | None
    pr_number: int | None
    pr_url: str | None


def _snapshot(
    run_id: str, proposal: PublicationProposal, *, mode: StagedPublicationValidationMode
) -> _PublicationSnapshot:
    def operation(
        integration: Integration,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        _lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> _PublicationSnapshot:
        return _PublicationSnapshot(
            integration=integration,
            input=_input(publication, proposal),
            status=publication.status,
            commit_sha=publication.github_commit_sha,
            pr_number=publication.pr_number,
            pr_url=publication.pr_url,
        )

    return with_validated_staged_draft_publication(run_id, operation, mode=mode)


def _revalidate_publication_authority(
    run_id: str,
    proposal: PublicationProposal,
    *,
    expected_status: str,
) -> None:
    """Check the caller-bound lease again immediately before a GitHub write."""

    def operation(
        _integration: Integration,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        _lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> None:
        _input(publication, proposal)
        if publication.status != expected_status:
            raise PublicationServiceError("publication claim changed before external publication")

    with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")


def _input(publication: TaskDraftPublication, proposal: PublicationProposal) -> DraftPublicationInput:
    if not proposal.operations:
        raise PublicationServiceError("publication proposal has no normalized operations")
    fields = (
        publication.repository,
        publication.base_sha,
        publication.base_branch,
        publication.branch,
        publication.expected_github_app_login,
        publication.expected_github_app_slug,
        publication.commit_message,
        publication.commit_author_name,
        publication.commit_author_email,
        publication.pr_title,
    )
    if (
        not all(isinstance(value, str) and value for value in fields)
        or not isinstance(publication.commit_timestamp, int)
        or not 0 < publication.commit_timestamp < 2**31
    ):
        raise PublicationServiceError("publication claim is missing a persisted binding")
    return DraftPublicationInput(
        repository=publication.repository,
        base_sha=publication.base_sha,
        base_branch=publication.base_branch,
        branch=publication.branch,
        expected_creator_login=publication.expected_github_app_login,
        expected_github_app_slug=publication.expected_github_app_slug,
        commit_message=publication.commit_message,
        commit_author_name=publication.commit_author_name,
        commit_author_email=publication.commit_author_email,
        commit_timestamp=publication.commit_timestamp,
        title=publication.pr_title,
        body=publication.pr_body,
        operations=proposal.operations,
    )


def _claim_update(
    run_id: str,
    proposal: PublicationProposal,
    *,
    mode: StagedPublicationValidationMode,
    update: Callable[[TaskDraftPublication, TaskPublicationLease], PublishedDraftPublication | None],
) -> PublishedDraftPublication | None:
    def operation(
        _integration: Integration,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> PublishedDraftPublication | None:
        _input(publication, proposal)
        return update(publication, lease)

    return with_validated_staged_draft_publication(run_id, operation, mode=mode)


def _record_commit(run_id: str, proposal: PublicationProposal, commit_sha: str) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if publication.status != TaskDraftPublication.Status.UPLOADED:
            raise PublicationServiceError("publication claim changed before commit recording")
        publication.status = TaskDraftPublication.Status.COMMIT_CREATED
        publication.github_commit_sha = commit_sha
        publication.commit_created_at = django_timezone.now()
        publication.save(update_fields=["status", "github_commit_sha", "commit_created_at", "updated_at"])
        return None

    _claim_update(run_id, proposal, mode="in_flight_mutation", update=update)


def _begin_branch_creation(run_id: str, proposal: PublicationProposal) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if publication.status != TaskDraftPublication.Status.COMMIT_CREATED:
            raise PublicationServiceError("branch creation was already attempted")
        publication.status = TaskDraftPublication.Status.BRANCH_CREATING
        publication.save(update_fields=["status", "updated_at"])
        return None

    _claim_update(run_id, proposal, mode="in_flight_mutation", update=update)


def _record_branch_creation(
    run_id: str,
    proposal: PublicationProposal,
    *,
    mode: StagedPublicationValidationMode = "in_flight_mutation",
) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if publication.status != TaskDraftPublication.Status.BRANCH_CREATING:
            raise PublicationServiceError("branch claim changed during publication")
        publication.status = TaskDraftPublication.Status.BRANCH_CREATED
        publication.branch_created_at = django_timezone.now()
        publication.save(update_fields=["status", "branch_created_at", "updated_at"])
        return None

    _claim_update(run_id, proposal, mode=mode, update=update)


def _begin_pr_creation(run_id: str, proposal: PublicationProposal) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if publication.status != TaskDraftPublication.Status.BRANCH_CREATED:
            raise PublicationServiceError("pull request creation was already attempted")
        publication.status = TaskDraftPublication.Status.PR_CREATING
        publication.pr_creation_started_at = django_timezone.now()
        publication.save(update_fields=["status", "pr_creation_started_at", "updated_at"])
        return None

    _claim_update(run_id, proposal, mode="continue_external_mutation", update=update)


def _record_published(
    run_id: str,
    proposal: PublicationProposal,
    pull_request: DraftPullRequest,
    *,
    mode: StagedPublicationValidationMode = "in_flight_mutation",
) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if (
            publication.status
            not in {TaskDraftPublication.Status.PR_CREATING, TaskDraftPublication.Status.PUBLICATION_UNKNOWN}
            or publication.github_commit_sha != pull_request.commit_sha
        ):
            raise PublicationServiceError("pull request claim changed during publication")
        reconciled_at = (
            django_timezone.now() if publication.status == TaskDraftPublication.Status.PUBLICATION_UNKNOWN else None
        )
        publication.status = TaskDraftPublication.Status.PUBLISHED
        publication.pr_number = pull_request.pr_number
        publication.pr_url = pull_request.pr_url
        publication.published_at = django_timezone.now()
        publication.publication_unknown_at = None
        publication.reconciled_at = reconciled_at
        publication.save(
            update_fields=[
                "status",
                "pr_number",
                "pr_url",
                "published_at",
                "publication_unknown_at",
                "reconciled_at",
                "updated_at",
            ]
        )
        return None

    _claim_update(run_id, proposal, mode=mode, update=update)


def _finalize(
    run_id: str, proposal: PublicationProposal, *, mode: StagedPublicationValidationMode
) -> PublishedDraftPublication:
    def update(publication: TaskDraftPublication, lease: TaskPublicationLease) -> PublishedDraftPublication:
        if publication.status == TaskDraftPublication.Status.FINALIZED:
            return _published_from_fields(publication.github_commit_sha, publication.pr_number, publication.pr_url)
        if publication.status != TaskDraftPublication.Status.PUBLISHED:
            raise PublicationServiceError("publication is not ready to finalize")
        result = _published_from_fields(publication.github_commit_sha, publication.pr_number, publication.pr_url)
        now = django_timezone.now()
        publication.status = TaskDraftPublication.Status.FINALIZED
        publication.finalized_at = now
        publication.save(update_fields=["status", "finalized_at", "updated_at"])
        lease.status = TaskPublicationLease.Status.FINALIZED
        lease.consumed_at = now
        lease.finalized_at = now
        lease.final_artifact_ref = result.pr_url
        lease.save(update_fields=["status", "consumed_at", "finalized_at", "final_artifact_ref", "updated_at"])
        return result

    result = _claim_update(run_id, proposal, mode=mode, update=update)
    assert result is not None
    return result


def _reconcile_pull_request(
    run_id: str,
    proposal: PublicationProposal,
    snapshot: _PublicationSnapshot,
    client: GitHubPublicationClient,
    transport: PublicationTransport,
) -> PublishedDraftPublication:
    if snapshot.commit_sha is None:
        raise PublicationServiceError("unknown publication claim has no server commit")
    branch = transport.reconcile_branch(client, snapshot.input, expected_branch_sha=snapshot.commit_sha)
    if branch is None:
        raise PublicationServiceError("unknown publication claim has no exact server branch")
    pull_request = transport.reconcile(client, snapshot.input, expected_branch_sha=snapshot.commit_sha)
    if pull_request is None:
        raise PublicationServiceError("unknown publication claim has no exact draft pull request")
    _record_published(run_id, proposal, pull_request, mode="reconcile_after_expiry")
    return _finalize(run_id, proposal, mode="reconcile_after_expiry")


def _mark_unknown(run_id: str, proposal: PublicationProposal, *, expected_status: str) -> None:
    def update(publication: TaskDraftPublication, _lease: TaskPublicationLease) -> None:
        if publication.status != expected_status:
            return None
        publication.status = TaskDraftPublication.Status.PUBLICATION_UNKNOWN
        publication.publication_unknown_at = django_timezone.now()
        publication.save(update_fields=["status", "publication_unknown_at", "updated_at"])
        return None

    _claim_update(run_id, proposal, mode="reconcile_after_expiry", update=update)


def _published(snapshot: _PublicationSnapshot) -> PublishedDraftPublication:
    return _published_from_fields(snapshot.commit_sha, snapshot.pr_number, snapshot.pr_url)


def _published_from_fields(
    commit_sha: str | None, pr_number: int | None, pr_url: str | None
) -> PublishedDraftPublication:
    if not isinstance(commit_sha, str) or not isinstance(pr_number, int) or not isinstance(pr_url, str):
        raise PublicationServiceError("publication claim lacks authoritative pull request fields")
    return PublishedDraftPublication(commit_sha=commit_sha, pr_number=pr_number, pr_url=pr_url)


def _github_client(integration: Integration) -> GitHubPublicationClient:
    return GitHubIntegration(integration, source="tasks_publication")
