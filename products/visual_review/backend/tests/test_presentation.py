"""Integration tests for visual_review DRF views."""

from urllib.parse import quote
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.visual_review.backend import logic
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES, VisualReviewTeamScopedTestMixin


class TestRepoViewSet(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_create_repo(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/repos/",
            {"repo_external_id": 12345, "repo_full_name": "org/my-repo"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["repo_full_name"] == "org/my-repo"
        assert data["repo_external_id"] == 12345
        assert "id" in data

    def test_list_repos(self):
        existing_count = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/").json()["count"]
        api.create_repo(team_id=self.team.id, repo_external_id=111, repo_full_name="org/first")
        api.create_repo(team_id=self.team.id, repo_external_id=222, repo_full_name="org/second")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] - existing_count == 2

    def test_retrieve_project(self):
        repo = api.create_repo(team_id=self.team.id, repo_external_id=333, repo_full_name="org/test")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{repo.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["repo_full_name"] == "org/test"

    def test_retrieve_project_not_found(self):
        import uuid

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{uuid.uuid4()}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRunViewSet(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.vr_project = api.create_repo(team_id=self.team.id, repo_external_id=99999, repo_full_name="org/test")

    @patch("products.visual_review.backend.storage.ArtifactStorage.get_presigned_upload_url")
    def test_create_run(self, mock_presigned):
        mock_presigned.return_value = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "value"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/",
            {
                "repo_id": str(self.vr_project.id),
                "run_type": "storybook",
                "commit_sha": "abc123def456789",
                "branch": "main",
                "pr_number": 42,
                "snapshots": [
                    {"identifier": "Button-primary", "content_hash": "hash1", "width": 100, "height": 200},
                    {"identifier": "Card-default", "content_hash": "hash2", "width": 150, "height": 250},
                ],
                "baseline_hashes": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "run_id" in data
        assert "uploads" in data
        assert len(data["uploads"]) == 2
        upload_hashes = {u["content_hash"] for u in data["uploads"]}
        assert upload_hashes == {"hash1", "hash2"}

    def test_retrieve_run(self):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            ),
            team_id=self.team.id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["commit_sha"] == "abc123"
        assert data["status"] == "pending"

    def test_get_run_snapshots(self):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="h1"),
                    SnapshotManifestItem(identifier="Card", content_hash="h2"),
                ],
            ),
            team_id=self.team.id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/snapshots/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"]
        assert len(results) == 2
        identifiers = {s["identifier"] for s in results}
        assert identifiers == {"Button", "Card"}

    @parameterized.expand(
        [
            ("excluded_by_default", "", {"Card"}),
            ("included_when_requested", "?include_quarantined=true", {"Button", "Card"}),
        ]
    )
    def test_get_run_snapshots_quarantine_visibility(self, _name, query, expected_identifiers):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="h1"),
                    SnapshotManifestItem(identifier="Card", content_hash="h2"),
                ],
            ),
            team_id=self.team.id,
        )
        logic.quarantine_identifier(
            repo_id=self.vr_project.id,
            identifier="Button",
            run_type=RunType.STORYBOOK,
            reason="flaky",
            user_id=self.user.id,
            team_id=self.team.id,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/snapshots/{query}"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert {s["identifier"] for s in data["results"]} == expected_identifiers
        assert data["quarantined_count"] == 1

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run_no_changes(self, mock_delay):
        """Runs with no changes complete immediately without triggering diff task."""
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            ),
            team_id=self.team.id,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/complete/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "completed"
        mock_delay.assert_not_called()

    def test_approve_run(self):
        # Create artifact directly via logic (API no longer exposes register_artifact)
        logic.get_or_create_artifact(
            repo_id=self.vr_project.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )

        # Create run with changed snapshot
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=self.team.id,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/approve/",
            {
                "snapshots": [{"identifier": "Button", "new_hash": "new_hash"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        # Per-snapshot approval is DB only — run not finalized
        assert not response.json()["approved"]

    def test_finalize_run(self):
        logic.get_or_create_artifact(
            repo_id=self.vr_project.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=self.team.id,
        )
        with (
            patch(
                "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            logic.complete_run(create_result.run_id)
        logic.finish_processing(create_result.run_id)

        # No PR on this run, so nothing is pushed, but approve_all + finalize marks it approved.
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/finalize/",
            {"approve_all": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["run"]["approved"]

    def _changed_snapshot_for_tolerate(self) -> tuple[str, str]:
        logic.get_or_create_artifact(
            repo_id=self.vr_project.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=self.team.id,
        )
        snapshot = RunSnapshot.objects.get(run_id=create_result.run_id, identifier="Button")
        # The diff pipeline normally classifies the snapshot — short-circuit it here
        # so the test stays a permission-boundary test rather than an integration test.
        snapshot.result = SnapshotResult.CHANGED
        snapshot.save(update_fields=["result"])
        return str(create_result.run_id), str(snapshot.id)

    @parameterized.expand(
        [
            ("session_auth", None, status.HTTP_200_OK),
            ("personal_api_key_write_scope", "visual_review:write", status.HTTP_200_OK),
            ("personal_api_key_read_scope", "visual_review:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_mark_tolerated_permission_boundary(self, _name: str, scope: str | None, expected_status: int):
        run_id, snapshot_id = self._changed_snapshot_for_tolerate()

        if scope is not None:
            key = self.create_personal_api_key_with_scopes([scope])
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/{run_id}/tolerate/",
            {"snapshot_id": snapshot_id},
            format="json",
        )

        assert response.status_code == expected_status, response.json()

    def _seed_history_row(
        self,
        sha: str,
        branch: str,
        content_hash: str,
        *,
        baseline_content_hash: str | None = None,
        run_type: str = RunType.STORYBOOK,
        run_status: str = RunStatus.COMPLETED,
        result: str = SnapshotResult.UNCHANGED,
    ) -> RunSnapshot:
        """Create one Run + one RunSnapshot directly, with full control over result and status."""
        artifact, _ = logic.get_or_create_artifact(
            repo_id=self.vr_project.id,
            content_hash=content_hash,
            storage_path=f"visual_review/{content_hash}",
        )
        # History dedup keys on `baseline_artifact_id`, so tests must seed it.
        # Default to the same artifact as `current_` for trivial cases.
        baseline_artifact = artifact
        if baseline_content_hash is not None and baseline_content_hash != content_hash:
            baseline_artifact, _ = logic.get_or_create_artifact(
                repo_id=self.vr_project.id,
                content_hash=baseline_content_hash,
                storage_path=f"visual_review/{baseline_content_hash}",
            )
        # Only one un-superseded run per (repo, branch, run_type) is allowed (partial unique
        # index). Supersede the prior latest with the new run's id before insert.
        new_id = uuid4()
        Run.objects.filter(
            repo_id=self.vr_project.id, branch=branch, run_type=run_type, superseded_by_id__isnull=True
        ).update(superseded_by_id=new_id)
        run = Run.objects.create(
            id=new_id,
            repo_id=self.vr_project.id,
            team_id=self.team.id,
            run_type=run_type,
            commit_sha=sha,
            branch=branch,
            status=run_status,
        )
        return RunSnapshot.objects.create(
            run=run,
            team_id=self.team.id,
            identifier="Button",
            current_hash=content_hash,
            current_artifact=artifact,
            baseline_artifact=baseline_artifact,
            result=result,
        )

    def _history_url(self, identifier: str, run_type: str = RunType.STORYBOOK) -> str:
        return (
            f"/api/projects/{self.team.id}/visual_review/repos/{self.vr_project.id}"
            f"/snapshots/{run_type}/{quote(identifier, safe='')}/"
        )

    def test_snapshot_history(self):
        """History returns one entry per *baseline transition* — every time
        the committed `.snapshots.yml` baseline actually moved.

        LAG-on-`baseline_artifact_id` (ASC) keeps the FIRST run of each
        baseline period, so the user sees the inception event plus every
        change since. Tolerated drift / pixel jitter (current_ flickers but
        baseline_ stays put) collapse naturally — no `result` filter needed.
        """
        # Two master runs sharing baseline `base-1` — collapse; the older
        # one is the inception event for that baseline period.
        self._seed_history_row(sha="aaa1111", branch="master", content_hash="hash-A", baseline_content_hash="base-1")
        self._seed_history_row(sha="aaa2222", branch="master", content_hash="hash-A", baseline_content_hash="base-1")
        # New baseline on main — distinct entry (transition to base-2).
        self._seed_history_row(
            sha="bbb1111",
            branch="main",
            content_hash="hash-B",
            baseline_content_hash="base-2",
            result=SnapshotResult.CHANGED,
        )
        # Tolerated drift on master: current_ flickers, baseline stays at
        # base-2 — must NOT create a new entry (the prod bug behind 252
        # fake events on a single tolerated-drift story).
        self._seed_history_row(
            sha="ddd0000", branch="master", content_hash="hash-jitter", baseline_content_hash="base-2"
        )

        # PR-branch run — filtered out by branch.
        self._seed_history_row(
            sha="ddd1111", branch="feat/something", content_hash="hash-feat", baseline_content_hash="base-3"
        )
        # Playwright run on master — filtered out by run_type.
        self._seed_history_row(
            sha="ccc1111",
            branch="master",
            content_hash="hash-pw",
            baseline_content_hash="base-pw",
            run_type=RunType.PLAYWRIGHT,
        )
        # Pending master run — filtered out by status (no baseline_artifact yet).
        self._seed_history_row(
            sha="eee1111",
            branch="master",
            content_hash="hash-pending",
            baseline_content_hash="base-pending",
            run_status=RunStatus.PENDING,
            result=SnapshotResult.NEW,
        )

        response = self.client.get(self._history_url("Button"))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        results = body["results"]
        # Two baseline transitions: aaa1111 (inception, base-1) and bbb1111
        # (transition to base-2). aaa2222 collapses into aaa1111's period;
        # ddd0000 collapses into bbb1111's.
        assert body["count"] == 2
        # Output is newest-first.
        assert results[0]["commit_sha"] == "bbb1111"
        assert results[1]["commit_sha"] == "aaa1111"
        for entry in results:
            assert "snapshot_id" in entry
            assert "review_state" in entry
            assert "diff_percentage" in entry

    def test_snapshot_history_with_special_chars_in_identifier(self):
        """Identifiers with `--`, spaces and dots round-trip via percent-encoding.

        Note: identifiers containing `/` are NOT supported with this encoding scheme —
        ASGI servers decode `%2F` to `/` before URL routing, breaking the path regex.
        Don't ship snapshot identifiers with literal slashes.
        """
        response = self.client.get(self._history_url("Components-Button--default v2.0"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 0
