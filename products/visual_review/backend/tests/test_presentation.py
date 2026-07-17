"""Integration tests for visual_review DRF views."""

from urllib.parse import quote, urlencode
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.helpers.trigram_search import MAX_SEARCH_LENGTH

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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["repo_full_name"], "org/my-repo")
        self.assertEqual(data["repo_external_id"], 12345)
        self.assertIn("id", data)

    def test_list_repos(self):
        existing_count = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/").json()["count"]
        api.create_repo(team_id=self.team.id, repo_external_id=111, repo_full_name="org/first")
        api.create_repo(team_id=self.team.id, repo_external_id=222, repo_full_name="org/second")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"] - existing_count, 2)

    def test_retrieve_project(self):
        repo = api.create_repo(team_id=self.team.id, repo_external_id=333, repo_full_name="org/test")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{repo.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repo_full_name"], "org/test")

    def test_retrieve_project_not_found(self):
        import uuid

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("run_id", data)
        self.assertIn("uploads", data)
        self.assertEqual(len(data["uploads"]), 2)
        upload_hashes = {u["content_hash"] for u in data["uploads"]}
        self.assertEqual(upload_hashes, {"hash1", "hash2"})

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["commit_sha"], "abc123")
        self.assertEqual(data["status"], "pending")

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data["results"]
        self.assertEqual(len(results), 2)
        identifiers = {s["identifier"] for s in results}
        self.assertEqual(identifiers, {"Button", "Card"})

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "completed")
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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Per-snapshot approval is DB only — run not finalized
        self.assertFalse(response.json()["approved"])

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["run"]["approved"])

    @parameterized.expand(
        [
            ("add_images_true", {"approve_all": True, "add_images_to_comment_on_pr": True}, True),
            ("add_images_false", {"approve_all": True, "add_images_to_comment_on_pr": False}, False),
            ("add_images_default", {"approve_all": True}, False),
        ]
    )
    def test_finalize_run_always_comments_and_forwards_add_images(
        self, _name: str, body: dict, expect_add_images: bool
    ):
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

        with (
            patch("products.visual_review.backend.logic._post_commit_status"),
            patch("products.visual_review.backend.logic.transaction.on_commit", side_effect=lambda fn, *a, **k: fn()),
            patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay") as delay,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/finalize/",
                body,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The comment is always dispatched; the flag only forwards whether to embed images.
        self.assertTrue(delay.called)
        self.assertEqual(delay.call_args.args[2], expect_add_images)

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        results = body["results"]
        # Two baseline transitions: aaa1111 (inception, base-1) and bbb1111
        # (transition to base-2). aaa2222 collapses into aaa1111's period;
        # ddd0000 collapses into bbb1111's.
        self.assertEqual(body["count"], 2)
        # Output is newest-first.
        self.assertEqual(results[0]["commit_sha"], "bbb1111")
        self.assertEqual(results[1]["commit_sha"], "aaa1111")
        for entry in results:
            self.assertIn("snapshot_id", entry)
            self.assertIn("review_state", entry)
            self.assertIn("diff_percentage", entry)

    def test_snapshot_history_with_special_chars_in_identifier(self):
        """Identifiers with `--`, spaces and dots round-trip via percent-encoding.

        Note: identifiers containing `/` are NOT supported with this encoding scheme —
        ASGI servers decode `%2F` to `/` before URL routing, breaking the path regex.
        Don't ship snapshot identifiers with literal slashes.
        """
        response = self.client.get(self._history_url("Components-Button--default v2.0"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)


class TestRepoRunsSearch(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.vr_project = api.create_repo(team_id=self.team.id, repo_external_id=88888, repo_full_name="org/searchtest")
        # Two completed runs with no changes — both land in the "clean" review state.
        self.run_login = Run.objects.create(
            repo_id=self.vr_project.id,
            team_id=self.team.id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc1234deadbeefcafef00d",
            branch="feature/login",
            pr_number=101,
            status=RunStatus.COMPLETED,
        )
        self.run_logout = Run.objects.create(
            repo_id=self.vr_project.id,
            team_id=self.team.id,
            run_type=RunType.PLAYWRIGHT,
            commit_sha="fed9876feedface00112233",
            branch="fix/logout",
            pr_number=202,
            status=RunStatus.COMPLETED,
        )

    def _runs_url(self, **params: str) -> str:
        base = f"/api/projects/{self.team.id}/visual_review/repos/{self.vr_project.id}/runs/"
        if not params:
            return base
        return f"{base}?{urlencode(params)}"

    def _team_runs_url(self, **params: str) -> str:
        base = f"/api/projects/{self.team.id}/visual_review/runs/"
        if not params:
            return base
        return f"{base}?{urlencode(params)}"

    def _branches(self, response_json: dict) -> set[str]:
        return {run["branch"] for run in response_json["results"]}

    @parameterized.expand(
        [
            # Exact substring on branch ("feature" stays below the fuzzy threshold for fix/logout).
            ("branch_substring", "feature", {"feature/login"}),
            # Exact substring on run type.
            ("run_type", "playwright", {"fix/logout"}),
            # Commit SHA matches by prefix.
            ("commit_sha_prefix", "abc1234", {"feature/login"}),
            # A substring that is not a prefix of the SHA must not match (prefix, not substring).
            ("commit_sha_mid_substring_excluded", "deadbeef", set()),
            # PR number matches exactly.
            ("pr_number", "101", {"feature/login"}),
            # Case-insensitive.
            ("case_insensitive", "FEATURE", {"feature/login"}),
            # A typo in the branch still matches via trigram similarity.
            ("fuzzy_branch_typo", "featuer", {"feature/login"}),
            # A typo in the run type still matches via trigram similarity.
            ("fuzzy_run_type_typo", "storybok", {"feature/login"}),
            ("no_match", "zzzznomatch", set()),
        ]
    )
    def test_search_filters_runs(self, _name: str, search: str, expected_branches: set[str]):
        response = self.client.get(self._runs_url(search=search))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._branches(response.json()), expected_branches)

    def test_exact_matches_hide_fuzzy_matches_and_set_match_type(self):
        # "login" is a substring of feature/login (exact) and a fuzzy match for fix/logout (similar).
        # With an exact match present, the fuzzy-only match is suppressed.
        results = self.client.get(self._runs_url(search="login")).json()["results"]

        self.assertEqual([run["branch"] for run in results], ["feature/login"])
        self.assertEqual([run["search_match_type"] for run in results], ["exact"])

    def test_match_type_is_null_without_search(self):
        results = self.client.get(self._runs_url()).json()["results"]

        self.assertTrue(results)
        self.assertTrue(all(run["search_match_type"] is None for run in results))

    def test_blank_search_returns_all_runs(self):
        response = self.client.get(self._runs_url(search=""))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._branches(response.json()), {"feature/login", "fix/logout"})

    def test_search_composes_with_review_state(self):
        """Search narrows within whichever review state is active, not the whole repo."""
        both = self.client.get(self._runs_url(review_state="clean"))
        self.assertEqual(self._branches(both.json()), {"feature/login", "fix/logout"})

        scoped = self.client.get(self._runs_url(review_state="clean", search="feature"))
        self.assertEqual(scoped.status_code, status.HTTP_200_OK)
        self.assertEqual(self._branches(scoped.json()), {"feature/login"})

        # A run that exists but is not in the requested state is excluded even on a match.
        other_state = self.client.get(self._runs_url(review_state="processing", search="feature"))
        self.assertEqual(self._branches(other_state.json()), set())

    def test_team_wide_endpoint_supports_search(self):
        # The project-wide endpoint (exposed as the MCP tool) shares the same search path.
        response = self.client.get(self._team_runs_url(search="feature"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._branches(response.json()), {"feature/login"})

    @parameterized.expand([("repo_scoped", "_runs_url"), ("team_wide", "_team_runs_url")])
    def test_overlong_search_is_rejected(self, _name: str, url_method: str):
        # Cap the term before it reaches the trigram comparison (pathological CPU cost).
        url = getattr(self, url_method)(search="x" * (MAX_SEARCH_LENGTH + 1))
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestRunFinalizePersonalAPIKeyScopes(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.vr_project = api.create_repo(team_id=self.team.id, repo_external_id=77777, repo_full_name="org/scope-test")

    def _auth(self, value: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {value}"}

    def test_finalize_allowed_with_visual_review_write_scope(self):
        key = self.create_personal_api_key_with_scopes(["visual_review:write"])
        # Target a non-existent UUID; a 404 proves the scope gate was passed.
        url = f"/api/projects/{self.team.id}/visual_review/runs/{uuid4()}/finalize/"
        response = self.client.post(url, {}, format="json", **self._auth(key))
        assert response.status_code != 403, response.json()

    @parameterized.expand(
        [
            ("read_scope_cannot_satisfy_write", ["visual_review:read"]),
            ("unrelated_scope", ["insight:read"]),
            ("no_scopes", []),
        ]
    )
    def test_finalize_rejected_without_visual_review_write_scope(self, _name: str, scopes: list[str]):
        key = self.create_personal_api_key_with_scopes(scopes)
        url = f"/api/projects/{self.team.id}/visual_review/runs/{uuid4()}/finalize/"
        response = self.client.post(url, {}, format="json", **self._auth(key))
        assert response.status_code == 403, response.json()
