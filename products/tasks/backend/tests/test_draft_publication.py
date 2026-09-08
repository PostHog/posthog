import os
import hashlib
import tempfile
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.user import User

from products.tasks.backend.facade.draft_publication import (
    DraftPublicationRequest,
    InvalidDraftPublicationError,
    get_draft_publication_lifecycle,
    publish_draft_publication,
    reserve_draft_publication,
    revoke_draft_publication,
)
from products.tasks.backend.facade.staged_execution import InvalidStagedTaskBindingError
from products.tasks.backend.logic.services.publication_bundle import (
    PublicationBundlePlan,
    build_publication_bundle,
    validate_publication_bundle,
)
from products.tasks.backend.logic.services.publication_policy import validate_bundle_acceptance_authority
from products.tasks.backend.logic.services.publication_service import (
    ValidatedBundleRecord,
    block_publication,
    record_validated_bundle,
)
from products.tasks.backend.models import Task, TaskDraftPublication, TaskRun, TaskStagedRun
from products.tasks.backend.temporal.publish_task_artifact import activities as publication_activities


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgSign=false", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        },
    )
    return result.stdout.strip()


class _LifecycleGitHub:
    def __init__(self, rejection: tuple[str, int] | None = None) -> None:
        self.requests: list[tuple[str, str]] = []
        self.branch_sha: str | None = None
        self.branch_response_is_ambiguous = True
        self.commit_response_is_ambiguous = True
        self.pull_request: dict[str, object] | None = None
        self.rejection = rejection

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> object:
        self.requests.append((method, path))
        if self.rejection is not None and method == self.rejection[0]:
            return {"status_code": self.rejection[1]}
        publication = TaskDraftPublication.objects.unscoped().get()
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": publication.base_sha}}
        if method == "GET" and path.endswith(f"/git/commits/{publication.base_sha}"):
            return {"sha": publication.base_sha, "tree": {"sha": publication.bundle_base_tree_sha}}
        if method == "POST" and path.endswith("/git/blobs"):
            content = str((json_body or {})["content"]).encode()
            sha = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": publication.bundle_head_tree_sha}
        if method == "POST" and path.endswith("/git/commits"):
            if self.commit_response_is_ambiguous:
                self.commit_response_is_ambiguous = False
                return {}
            return {"sha": "d" * 40}
        if method == "GET" and path.endswith("/git/commits/" + "d" * 40):
            identity = {
                "name": "PostHog Tasks",
                "email": "tasks@posthog.com",
                "date": datetime.fromtimestamp(int(publication.created_at.timestamp()), UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            return {
                "sha": "d" * 40,
                "message": publication.commit_message,
                "tree": {"sha": publication.bundle_head_tree_sha},
                "parents": [{"sha": publication.base_sha, "url": "https://api.github.com/commit"}],
                "author": identity,
                "committer": identity,
            }
        if method == "POST" and path.endswith("/git/refs"):
            self.branch_sha = str((json_body or {})["sha"])
            if self.branch_response_is_ambiguous:
                self.branch_response_is_ambiguous = False
                raise TimeoutError("accepted then disconnected")
            return {"ref": f"refs/heads/{publication.head_branch}", "object": {"sha": self.branch_sha}}
        if method == "GET" and "/git/ref/heads/codex/" in path:
            return {"object": {"sha": self.branch_sha}} if self.branch_sha else {"status_code": 404}
        if method == "POST" and path.endswith("/pulls"):
            self.pull_request = {
                "number": 17,
                "html_url": "https://github.com/Example/Repository/pull/17",
                "draft": True,
                "state": "open",
                "title": publication.pr_title,
                "body": publication.pr_body,
                "base": {
                    "ref": publication.base_branch,
                    "sha": publication.base_sha,
                    "repo": {"full_name": "Example/Repository"},
                },
                "head": {
                    "ref": publication.head_branch,
                    "sha": self.branch_sha,
                    "repo": {"full_name": "Example/Repository"},
                },
            }
            return self.pull_request
        if method == "GET" and "/pulls/" in path:
            return self.pull_request or {}
        if method == "GET" and path.endswith("/pulls"):
            return [self.pull_request] if self.pull_request else []
        raise AssertionError(f"unexpected request: {method} {path}")


def _build_shallow_clone_bundle(publication: TaskDraftPublication) -> tuple[bytes, ValidatedBundleRecord]:
    execution = publication.staged_run.execution_run
    assert execution is not None
    execution.status = TaskRun.Status.COMPLETED
    execution.save(update_fields=["status"])
    with tempfile.TemporaryDirectory(prefix="task-publication-test-") as raw:
        root = Path(raw)
        origin = root / "origin"
        origin.mkdir()
        _git(origin, "init")
        (origin / "safe.txt").write_text("base\n")
        _git(origin, "add", "safe.txt")
        _git(origin, "commit", "-m", "base")
        _git(origin, "branch", "-M", "feature/pulse")
        workspace = root / "workspace"
        _git(root, "clone", "--depth", "1", "--branch", "feature/pulse", f"file://{origin}", str(workspace))
        publication.base_sha = _git(workspace, "rev-parse", "HEAD")
        publication.staged_run.base_sha = publication.base_sha
        publication.staged_run.save(update_fields=["base_sha"])
        publication.save(update_fields=["base_sha"])
        (workspace / "safe.txt").write_text("changed\n")
        exports = root / "exports"
        exports.mkdir(mode=0o700)
        plan = PublicationBundlePlan(
            workspace_path=workspace,
            export_root=exports,
            repository=publication.repository,
            base_commit=publication.base_sha,
            commit_message=publication.commit_message,
            commit_timestamp=int(publication.created_at.timestamp()),
        )
        artifact = build_publication_bundle(plan)
        bundle = artifact.bundle_path.read_bytes()
        validated = validate_publication_bundle(bundle, plan)
    return bundle, ValidatedBundleRecord(
        storage_ref=f"tasks/draft-publications/{publication.id}/publication.bundle",
        sha256=hashlib.sha256(bundle).hexdigest(),
        byte_count=len(bundle),
        artifact_head_sha=validated.artifact_head_sha,
        base_tree_sha=validated.base_tree_sha,
        head_tree_sha=validated.head_tree_sha,
        gate_summary_ref=f"tasks/draft-publications/{publication.id}/git-diff-check.log",
    )


class TestDraftPublication(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Draft publication org")
        self.team = Team.objects.create(organization=organization, name="Draft publication team")
        self.user = User.objects.create(email="draft-publication@example.com")
        OrganizationMembership.objects.create(organization=organization, user=self.user)
        self.caller_id = uuid4()
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Make a safe change",
            description="Prepare a reviewed change without publishing it directly.",
            origin_product="task_analysis",
        )
        analysis_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)
        execution_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        self.staged_run = TaskStagedRun.objects.for_team(self.team.id).create(
            team=self.team,
            caller_id=self.caller_id,
            task=task,
            analysis_run=analysis_run,
            execution_run=execution_run,
            repository="example/repository",
            base_sha="a" * 40,
            base_branch="main",
            github_integration_id=1,
            github_user_integration_id=uuid4(),
            github_installation_id="installation-1",
            grant_version="v1",
            analysis_manifest={
                "version": 1,
                "phase": "analysis",
                "mcp_scope_preset": "read_only",
                "disabled_tools": [],
            },
            execution_manifest={"version": 1, "phase": "execution", "mcp_scope_preset": "full", "disabled_tools": []},
            create_idempotency_key="create-key",
            advance_idempotency_key="advance-key",
        )

    def _request(self, *, logical_artifact_key: str = "artifact-1") -> DraftPublicationRequest:
        now = timezone.now()
        return DraftPublicationRequest(
            team_id=self.team.id,
            caller_id=self.caller_id,
            staged_run_id=self.staged_run.id,
            logical_artifact_key=logical_artifact_key,
            commit_message="feat(tasks): publish a safe change",
            pr_title="Publish a safe change",
            pr_body="A synthetic draft pull request.",
            starts_before=now + timedelta(minutes=5),
            expires_at=now + timedelta(hours=1),
        )

    def test_reservation_replays_only_the_same_authoritative_request(self) -> None:
        request = self._request()

        first = reserve_draft_publication(request)
        second = reserve_draft_publication(request)

        assert first == second

        with pytest.raises(InvalidDraftPublicationError):
            reserve_draft_publication(self._request(logical_artifact_key="different-artifact"))

    @parameterized.expand(
        [
            ("queued", TaskRun.Status.QUEUED, True),
            ("in_progress", TaskRun.Status.IN_PROGRESS, True),
            ("completed", TaskRun.Status.COMPLETED, False),
        ]
    )
    def test_reservation_only_before_execution_completion(self, _name: str, status: str, allowed: bool) -> None:
        execution = self.staged_run.execution_run
        assert execution is not None
        execution.status = status
        execution.save(update_fields=["status"])

        if allowed:
            assert reserve_draft_publication(self._request()).status == "pending"
        else:
            with pytest.raises(InvalidDraftPublicationError, match="eligible"):
                reserve_draft_publication(self._request())

    def test_completed_publication_lookup_locks_staged_run_and_finds_reservation(self) -> None:
        reserved = reserve_draft_publication(self._request())
        execution = self.staged_run.execution_run
        assert execution is not None
        execution.status = TaskRun.Status.COMPLETED
        execution.save(update_fields=["status"])

        with CaptureQueriesContext(connection) as queries:
            result = publication_activities.resolve_completed_publication(str(execution.id))

        assert result == publication_activities.PublishTaskArtifactInput(
            staged_run_id=self.staged_run.id, publication_id=reserved.publication_id
        )
        assert any("FOR UPDATE" in query["sql"] for query in queries.captured_queries)

    def test_revocation_remains_terminal_for_a_publication_retry(self) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        publication.status = TaskDraftPublication.Status.UNKNOWN
        publication.save(update_fields=["status"])

        assert revoke_draft_publication(team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id)
        result = publish_draft_publication(
            team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
        )

        assert result.status == "revoked"

    def test_stale_failure_transition_cannot_overwrite_revocation(self) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)

        revoke_draft_publication(team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id)

        assert not block_publication(publication)
        publication.refresh_from_db()
        assert publication.status == TaskDraftPublication.Status.REVOKED

    def test_revoked_repository_grant_blocks_bundle_acceptance(self) -> None:
        reserved = reserve_draft_publication(self._request())
        execution = self.staged_run.execution_run
        assert execution is not None
        execution.status = TaskRun.Status.COMPLETED
        execution.save(update_fields=["status"])
        record = ValidatedBundleRecord(
            storage_ref="tasks/draft-publications/test/publication.bundle",
            sha256="a" * 64,
            byte_count=1,
            artifact_head_sha="b" * 40,
            base_tree_sha="c" * 40,
            head_tree_sha="d" * 40,
            gate_summary_ref="tasks/draft-publications/test/gate.log",
        )
        with (
            patch(
                "products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant",
                side_effect=InvalidStagedTaskBindingError("revoked"),
            ),
            pytest.raises(InvalidDraftPublicationError, match="grant"),
        ):
            record_validated_bundle(
                team_id=self.team.id,
                caller_id=self.caller_id,
                publication_id=reserved.publication_id,
                bundle=record,
            )

        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        assert publication.status == TaskDraftPublication.Status.BLOCKED

    def test_bundle_acceptance_rechecks_the_stored_personal_integration(self) -> None:
        """Break caught: publication validates only the team installation after actor consent changes."""
        personal_integration_id = uuid4()
        self.staged_run.github_user_integration_id = personal_integration_id
        self.staged_run.save(update_fields=["github_user_integration_id", "updated_at"])
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        execution = self.staged_run.execution_run
        assert execution is not None
        execution.status = TaskRun.Status.COMPLETED
        execution.save(update_fields=["status"])

        with patch(
            "products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant"
        ) as revalidate:
            validate_bundle_acceptance_authority(publication)

        assert revalidate.call_args.kwargs == {
            "team_id": self.team.id,
            "actor_id": self.user.id,
            "repository": "example/repository",
            "github_integration_id": 1,
            "github_user_integration_id": personal_integration_id,
            "github_installation_id": "installation-1",
        }

    def test_shallow_clone_resumes_claim_and_ambiguity_without_repeating_branch_or_pr(self) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        bundle, record = _build_shallow_clone_bundle(publication)
        github = _LifecycleGitHub()
        with (
            patch("products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant"),
            patch(
                "products.tasks.backend.logic.services.publication_service.object_storage.read_bytes",
                return_value=bundle,
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service._get_github_token",
                return_value="server-token",
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service.ServerGitHubPublicationClient",
                return_value=github,
            ),
        ):
            record_validated_bundle(
                team_id=self.team.id,
                caller_id=self.caller_id,
                publication_id=publication.id,
                bundle=record,
            )
            publication.claimed_at = timezone.now()
            publication.starts_before = timezone.now() - timedelta(seconds=1)
            publication.save(update_fields=["claimed_at", "starts_before"])
            first = publish_draft_publication(
                team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
            )
            second = publish_draft_publication(
                team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
            )
            third = publish_draft_publication(
                team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
            )

        assert first.status == "unknown"
        assert second.status == "unknown"
        assert third.status == "published"
        assert third.pr_number == 17
        assert github.requests.count(("POST", "/repos/example/repository/git/commits")) == 2
        assert github.requests.count(("POST", "/repos/example/repository/git/refs")) == 1
        assert github.requests.count(("POST", "/repos/example/repository/pulls")) == 1

    def test_initial_claim_blocks_when_start_deadline_passes_after_validation(self) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        bundle, record = _build_shallow_clone_bundle(publication)
        deadline = publication.starts_before
        github = _LifecycleGitHub()
        before_deadline = iter([deadline - timedelta(seconds=1)])

        def advancing_now() -> datetime:
            return next(before_deadline, deadline + timedelta(seconds=1))

        with patch("products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant"):
            record_validated_bundle(
                team_id=self.team.id,
                caller_id=self.caller_id,
                publication_id=publication.id,
                bundle=record,
            )
        with (
            patch(
                "products.tasks.backend.logic.services.publication_service.timezone.now",
                side_effect=advancing_now,
            ),
            patch("products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant"),
            patch(
                "products.tasks.backend.logic.services.publication_service.object_storage.read_bytes",
                return_value=bundle,
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service._get_github_token",
                return_value="server-token",
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service.ServerGitHubPublicationClient",
                return_value=github,
            ),
        ):
            result = publish_draft_publication(
                team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
            )

        publication.refresh_from_db()
        assert result.status == "blocked"
        assert publication.status == TaskDraftPublication.Status.BLOCKED
        assert publication.claimed_at is None
        assert github.requests == []

    @parameterized.expand(
        [("read_unauthorized", "GET", 401), ("mutation_rejected", "POST", 400), ("forbidden", "POST", 403)]
    )
    def test_deterministic_github_rejections_block_publication(self, _name: str, method: str, status_code: int) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        bundle, record = _build_shallow_clone_bundle(publication)
        with (
            patch("products.tasks.backend.logic.services.publication_policy.validate_staged_repository_grant"),
            patch(
                "products.tasks.backend.logic.services.publication_service.object_storage.read_bytes",
                return_value=bundle,
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service._get_github_token",
                return_value="server-token",
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service.ServerGitHubPublicationClient",
                return_value=_LifecycleGitHub((method, status_code)),
            ),
        ):
            record_validated_bundle(
                team_id=self.team.id,
                caller_id=self.caller_id,
                publication_id=publication.id,
                bundle=record,
            )
            with pytest.raises(InvalidDraftPublicationError):
                publish_draft_publication(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    publication_id=publication.id,
                )

        publication.refresh_from_db()
        assert publication.status == TaskDraftPublication.Status.BLOCKED

    @parameterized.expand(
        [
            ("merged", "2026-09-08T10:30:00Z", "merged", datetime(2026, 9, 8, 10, 30, tzinfo=UTC)),
            ("missing_timestamp", None, "unknown", None),
            ("malformed_timestamp", "not-a-timestamp", "unknown", None),
            ("naive_timestamp", "2026-09-08T10:30:00", "unknown", None),
        ]
    )
    def test_publication_lifecycle_exposes_only_validated_merge_evidence(
        self, _name: str, merged_at: str | None, expected_state: str, expected_merged_at: datetime | None
    ) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        publication.status = TaskDraftPublication.Status.PUBLISHED
        publication.pr_number = 17
        publication.pr_url = "https://github.com/Example/Repository/pull/17"
        publication.github_commit_sha = "d" * 40
        publication.save(update_fields=["status", "pr_number", "pr_url", "github_commit_sha"])
        github = _LifecycleGitHub()
        github.pull_request = {
            "number": 17,
            "html_url": publication.pr_url,
            "state": "closed",
            "merged": True,
            "merged_at": merged_at,
            "base": {"ref": publication.base_branch, "repo": {"full_name": "Example/Repository"}},
            "head": {
                "ref": publication.head_branch,
                "sha": publication.github_commit_sha,
                "repo": {"full_name": "Example/Repository"},
            },
        }

        with (
            patch(
                "products.tasks.backend.logic.services.publication_service._get_github_token",
                return_value="server-token",
            ),
            patch(
                "products.tasks.backend.logic.services.publication_service.ServerGitHubPublicationClient",
                return_value=github,
            ),
        ):
            lifecycle = get_draft_publication_lifecycle(
                team_id=self.team.id, caller_id=self.caller_id, publication_id=publication.id
            )

        assert lifecycle.remote_state == expected_state
        assert lifecycle.merged_at == expected_merged_at

    @parameterized.expand(
        [
            ("unexported_pending", TaskDraftPublication.Status.PENDING, None, TaskDraftPublication.Status.BLOCKED),
            (
                "durable_pending",
                TaskDraftPublication.Status.PENDING,
                "tasks/draft-publications/test/publication.bundle",
                TaskDraftPublication.Status.PENDING,
            ),
            ("unknown", TaskDraftPublication.Status.UNKNOWN, None, TaskDraftPublication.Status.UNKNOWN),
            ("revoked", TaskDraftPublication.Status.REVOKED, None, TaskDraftPublication.Status.REVOKED),
            ("published", TaskDraftPublication.Status.PUBLISHED, None, TaskDraftPublication.Status.PUBLISHED),
        ]
    )
    def test_failed_child_finalizer_blocks_only_unexported_pending_publication(
        self, _name: str, status: str, bundle_ref: str | None, expected_status: str
    ) -> None:
        reserved = reserve_draft_publication(self._request())
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reserved.publication_id)
        publication.status = status
        publication.bundle_storage_ref = bundle_ref
        publication.save(update_fields=["status", "bundle_storage_ref"])

        publication_activities.finalize_failed_publication(
            publication_activities.PublishTaskArtifactInput(
                staged_run_id=self.staged_run.id, publication_id=publication.id
            )
        )

        publication.refresh_from_db()
        assert publication.status == expected_status
        assert (publication.blocked_at is not None) is (expected_status == TaskDraftPublication.Status.BLOCKED)
