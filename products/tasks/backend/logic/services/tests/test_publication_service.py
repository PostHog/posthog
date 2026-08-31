from datetime import datetime
from types import SimpleNamespace

import pytest

from posthog.egress.limiter.policies import Priority
from posthog.models import Integration

from products.tasks.backend.logic.services import publication_service
from products.tasks.backend.logic.services.publication_service import (
    PublicationProposal,
    PublicationServiceError,
    get_staged_draft_publication_replay,
    publish_staged_draft_publication,
)
from products.tasks.backend.logic.services.publication_transport import (
    BranchCreation,
    DraftPublicationInput,
    DraftPullRequest,
    GitHubPublicationClient,
    GitHubResponse,
    NormalizedTreeOperation,
)
from products.tasks.backend.models import TaskDraftPublication, TaskPublicationLease


@pytest.fixture(autouse=True)
def allow_publication_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication_service, "require_successful_publication_gates", lambda _run_id: None)


class _Publication:
    def __init__(self, status: str) -> None:
        self.id = "publication-id"
        self.id = "publication-id"
        self.status = status
        self.repository = "posthog/posthog"
        self.base_sha = "a" * 40
        self.base_branch = "main"
        self.branch = "codex/0123456789abcdef0123456789abcdef"
        self.expected_github_app_login = "posthog-app[bot]"
        self.expected_github_app_slug = "posthog"
        self.commit_message = "feat: add report"
        self.commit_author_name = "PostHog Tasks"
        self.commit_author_email = "tasks@posthog.com"
        self.commit_timestamp = 1_000
        self.pr_title = "feat: add report"
        self.pr_body = "Creates one report."
        self.github_commit_sha: str | None = None
        self.pr_number: int | None = None
        self.pr_url: str | None = None
        self.bundle_storage_path: str | None = None
        self.bundle_head_sha: str | None = None
        self.bundle_sha256: str | None = None
        self.bundle_byte_count: int | None = None
        self.publication_unknown_at: datetime | None = None
        self.reconciled_at: datetime | None = None
        self.published_at: datetime | None = None
        self.finalized_at: datetime | None = None
        self.commit_created_at: datetime | None = None
        self.branch_created_at: datetime | None = None
        self.pr_creation_started_at: datetime | None = None

    def save(self, *, update_fields: list[str]) -> None:
        return None


class _UnusedGitHubClient:
    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
        priority: Priority | None = None,
        retry_transient: bool | None = None,
    ) -> GitHubResponse:
        raise AssertionError(f"Unexpected GitHub request: {method} {path}")


def _unused_client_factory(_integration: Integration) -> GitHubPublicationClient:
    return _UnusedGitHubClient()


class _Transport:
    def __init__(self, locked: list[bool], *, pull_request: DraftPullRequest | Exception | None = None) -> None:
        self.locked = locked
        self.pull_request = pull_request or DraftPullRequest(
            commit_sha="c" * 40,
            pr_number=42,
            pr_url="https://github.com/posthog/posthog/pull/42",
        )
        self.calls: list[str] = []

    def create_commit(self, _client: GitHubPublicationClient, _publication: DraftPublicationInput) -> str:
        assert not self.locked[0]
        self.calls.append("commit")
        return "c" * 40

    def create_branch(
        self, _client: GitHubPublicationClient, _publication: DraftPublicationInput, _commit_sha: str
    ) -> BranchCreation:
        assert not self.locked[0]
        self.calls.append("branch")
        return BranchCreation.CREATED

    def create_pull_request(
        self, _client: GitHubPublicationClient, _publication: DraftPublicationInput, _commit_sha: str
    ) -> DraftPullRequest:
        assert not self.locked[0]
        self.calls.append("pull_request")
        if isinstance(self.pull_request, Exception):
            raise self.pull_request
        return self.pull_request

    def reconcile(
        self,
        _client: GitHubPublicationClient,
        _publication: DraftPublicationInput,
        *,
        expected_branch_sha: str,
    ) -> DraftPullRequest | None:
        assert not self.locked[0]
        self.calls.append("reconcile_pr")
        assert expected_branch_sha == "c" * 40
        return self.pull_request if isinstance(self.pull_request, DraftPullRequest) else None

    def reconcile_branch(
        self,
        _client: GitHubPublicationClient,
        _publication: DraftPublicationInput,
        *,
        expected_branch_sha: str,
    ) -> BranchCreation | None:
        assert not self.locked[0]
        self.calls.append("reconcile_branch")
        assert expected_branch_sha == "c" * 40
        return BranchCreation.EXISTS_EXACT


def _proposal() -> PublicationProposal:
    return PublicationProposal(operations=(NormalizedTreeOperation(path="README.md", mode="100644", content=b"hello"),))


def _lock_publication(monkeypatch: pytest.MonkeyPatch, publication: _Publication) -> list[bool]:
    locked = [False]
    integration = SimpleNamespace(id=1)
    lease = SimpleNamespace(
        status=TaskPublicationLease.Status.ACTIVE,
        consumed_at=None,
        finalized_at=None,
        final_artifact_ref=None,
        save=lambda **_kwargs: None,
    )

    def locked_helper(run_id: str, operation: object, *, mode: str) -> object:
        assert run_id == "run-id"
        assert callable(operation)
        locked[0] = True
        try:
            return operation(integration, object(), object(), object(), object(), lease, publication)
        finally:
            locked[0] = False

    monkeypatch.setattr(publication_service, "with_validated_staged_draft_publication", locked_helper)
    return locked


def test_publishes_once_with_every_external_call_outside_the_locked_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.UPLOADED)
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)

    result = publish_staged_draft_publication(
        "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
    )

    assert result.pr_url == "https://github.com/posthog/posthog/pull/42"
    assert transport.calls == ["commit", "branch", "pull_request"]
    assert publication.status == TaskDraftPublication.Status.FINALIZED


def test_revalidates_server_gate_before_any_publication_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.UPLOADED)
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)
    checked: list[str] = []

    publish_staged_draft_publication(
        "run-id",
        _proposal(),
        transport=transport,
        client_factory=_unused_client_factory,
        gate_validator=checked.append,
    )

    assert checked == ["run-id"]
    assert transport.calls == ["commit", "branch", "pull_request"]


def test_revocation_after_branch_intent_prevents_branch_and_pull_request_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = _Publication(TaskDraftPublication.Status.UPLOADED)
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)
    revoked = [False]
    original_begin_branch_creation = publication_service._begin_branch_creation
    original_revalidation = publication_service._revalidate_publication_authority

    def begin_branch_creation(run_id: str, proposal: PublicationProposal) -> None:
        original_begin_branch_creation(run_id, proposal)
        revoked[0] = True

    def revalidate_publication(run_id: str, proposal: PublicationProposal, *, expected_status: str) -> None:
        if revoked[0]:
            raise PublicationServiceError("staged capabilities revoked")
        original_revalidation(run_id, proposal, expected_status=expected_status)

    monkeypatch.setattr(publication_service, "_begin_branch_creation", begin_branch_creation)
    monkeypatch.setattr(publication_service, "_revalidate_publication_authority", revalidate_publication)

    with pytest.raises(PublicationServiceError, match="server branch outcome is unknown"):
        publish_staged_draft_publication(
            "run-id",
            _proposal(),
            transport=transport,
            client_factory=_unused_client_factory,
        )

    assert transport.calls == ["commit"]
    assert publication.status == TaskDraftPublication.Status.PUBLICATION_UNKNOWN


def test_pr_attempt_retry_reconciles_without_a_second_post(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.PR_CREATING)
    publication.github_commit_sha = "c" * 40
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)

    result = publish_staged_draft_publication(
        "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
    )

    assert result.pr_number == 42
    assert transport.calls == ["reconcile_branch", "reconcile_pr"]
    assert publication.status == TaskDraftPublication.Status.FINALIZED


def test_branch_creation_retry_never_reposts_the_ref_when_no_exact_branch_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = _Publication(TaskDraftPublication.Status.BRANCH_CREATING)
    publication.github_commit_sha = "c" * 40
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)
    monkeypatch.setattr(transport, "reconcile_branch", lambda *_args, **_kwargs: None)

    with pytest.raises(PublicationServiceError, match="no exact branch"):
        publish_staged_draft_publication(
            "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
        )

    assert transport.calls == []
    assert publication.status == TaskDraftPublication.Status.BRANCH_CREATING


def test_finalized_retry_returns_the_authoritative_pr_without_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.FINALIZED)
    publication.github_commit_sha = "c" * 40
    publication.pr_number = 42
    publication.pr_url = "https://github.com/posthog/posthog/pull/42"
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)

    result = publish_staged_draft_publication(
        "run-id",
        _proposal(),
        transport=transport,
        client_factory=lambda _integration: (_ for _ in ()).throw(
            AssertionError("finalized replay must not use egress")
        ),
    )

    assert result.pr_number == 42
    assert transport.calls == []


def test_replay_snapshot_returns_only_persisted_bundle_references(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.UPLOADED)
    publication.bundle_storage_path = "tasks/draft-publications/publication/bundle.bundle"
    publication.bundle_head_sha = "b" * 40
    publication.bundle_sha256 = "d" * 64
    publication.bundle_byte_count = 123
    _lock_publication(monkeypatch, publication)

    replay = get_staged_draft_publication_replay("run-id")

    assert replay.publication_id == "publication-id"
    assert replay.status == TaskDraftPublication.Status.UPLOADED
    assert replay.publication_id == "publication-id"
    assert replay.bundle_storage_path == publication.bundle_storage_path
    assert replay.bundle_byte_count == 123


def test_replay_checks_retained_external_state_before_in_flight_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = _Publication(TaskDraftPublication.Status.PUBLICATION_UNKNOWN)
    modes: list[str] = []

    def locked_helper(run_id: str, operation: object, *, mode: str) -> object:
        assert run_id == "run-id"
        assert callable(operation)
        modes.append(mode)
        return operation(
            SimpleNamespace(id=1),
            object(),
            object(),
            object(),
            object(),
            SimpleNamespace(),
            publication,
        )

    monkeypatch.setattr(publication_service, "with_validated_staged_draft_publication", locked_helper)

    replay = get_staged_draft_publication_replay("run-id")

    assert replay.status == TaskDraftPublication.Status.PUBLICATION_UNKNOWN
    assert modes == ["reconcile_after_expiry"]


def test_pr_post_failure_marks_unknown_and_retry_only_reconciles(monkeypatch: pytest.MonkeyPatch) -> None:
    publication = _Publication(TaskDraftPublication.Status.BRANCH_CREATED)
    publication.github_commit_sha = "c" * 40
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked, pull_request=TimeoutError())

    with pytest.raises(PublicationServiceError, match="outcome is unknown"):
        publish_staged_draft_publication(
            "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
        )

    assert publication.status == TaskDraftPublication.Status.PUBLICATION_UNKNOWN
    transport.pull_request = DraftPullRequest(
        commit_sha="c" * 40,
        pr_number=42,
        pr_url="https://github.com/posthog/posthog/pull/42",
    )
    result = publish_staged_draft_publication(
        "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
    )

    assert result.pr_number == 42
    assert transport.calls == ["pull_request", "reconcile_branch", "reconcile_pr"]


def test_failed_pr_attempt_does_not_regress_a_concurrently_finalized_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = _Publication(TaskDraftPublication.Status.BRANCH_CREATED)
    publication.github_commit_sha = "c" * 40
    locked = _lock_publication(monkeypatch, publication)
    transport = _Transport(locked)

    def fail_after_concurrent_finalize(
        _client: GitHubPublicationClient, _publication: DraftPublicationInput, _commit_sha: str
    ) -> DraftPullRequest:
        publication.status = TaskDraftPublication.Status.FINALIZED
        publication.pr_number = 42
        publication.pr_url = "https://github.com/posthog/posthog/pull/42"
        raise TimeoutError

    monkeypatch.setattr(transport, "create_pull_request", fail_after_concurrent_finalize)

    with pytest.raises(PublicationServiceError, match="outcome is unknown"):
        publish_staged_draft_publication(
            "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
        )

    assert publication.status == TaskDraftPublication.Status.FINALIZED


def test_resuming_a_created_branch_uses_the_external_continuation_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication = _Publication(TaskDraftPublication.Status.BRANCH_CREATED)
    publication.github_commit_sha = "c" * 40
    modes: list[str] = []
    integration = SimpleNamespace(id=1)
    lease = SimpleNamespace()

    def locked_helper(run_id: str, operation: object, *, mode: str) -> object:
        assert run_id == "run-id"
        assert callable(operation)
        modes.append(mode)
        if mode == "continue_external_mutation":
            raise PublicationServiceError("external continuation blocked")
        return operation(integration, object(), object(), object(), object(), lease, publication)

    monkeypatch.setattr(publication_service, "with_validated_staged_draft_publication", locked_helper)
    transport = _Transport([False])

    with pytest.raises(PublicationServiceError, match="external continuation blocked"):
        publish_staged_draft_publication(
            "run-id", _proposal(), transport=transport, client_factory=_unused_client_factory
        )

    assert modes == ["reconcile_after_expiry", "continue_external_mutation"]
    assert transport.calls == []
