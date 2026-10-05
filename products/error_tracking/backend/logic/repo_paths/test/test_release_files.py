from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import zstd
from parameterized import parameterized

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

from products.error_tracking.backend.logic import create_release, update_release
from products.error_tracking.backend.logic.repo_paths.git_lister import GitFetchTarget, GitHostNotAllowed, RepoFileList
from products.error_tracking.backend.logic.repo_paths.release_files import (
    RepoPathsRetryableError,
    StoredFileList,
    store_release_file_list,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OLDER_COMMITS = ["1" * 40, "2" * 40]
PATHS = ("services/api/manage.py", "apps/web/src/index.tsx", "README.md")


class _MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self._clock = datetime(2026, 1, 1, tzinfo=UTC)

    def put(self, key: str, content: bytes) -> None:
        self._clock += timedelta(minutes=1)
        self.objects[key] = (content, self._clock)

    def write(self, bucket: str, key: str, content: bytes, extras: dict[str, str] | None = None) -> None:
        self.put(key, content)

    def head_object(self, bucket: str, file_key: str) -> dict[str, datetime | int] | None:
        stored = self.objects.get(file_key)
        return {"LastModified": stored[1], "ContentLength": len(stored[0])} if stored else None

    head_object_strict = head_object

    def list_objects_last_modified(self, bucket: str, prefix: str) -> dict[str, datetime]:
        return {key: modified for key, (_, modified) in self.objects.items() if key.startswith(prefix)}

    def delete_objects(self, bucket: str, keys: list[str]) -> list[str]:
        for key in keys:
            self.objects.pop(key, None)
        return keys


@override_settings(OBJECT_STORAGE_ENABLED=True, ERROR_TRACKING_REPO_PATHS_KEEP_PER_REPO=2)
class TestStoreReleaseFileList(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = _MemoryObjectStorage()
        self.fetched: list[GitFetchTarget] = []
        patches = [
            patch("posthog.storage.object_storage.object_storage_client", return_value=self.storage),
            patch(
                "products.error_tracking.backend.logic.repo_paths.release_files.list_repository_files",
                side_effect=self._list,
            ),
            patch(
                "products.error_tracking.backend.logic.repo_paths.release_files.is_url_allowed",
                return_value=(True, None),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _list(self, target: GitFetchTarget) -> RepoFileList:
        self.fetched.append(target)
        return RepoFileList(commit=target.commit, paths=tuple(sorted(PATHS)), fetched_bytes=1, seconds=0.1)

    def _release(self, remote_url: str) -> str:
        metadata = {"git": {"remote_url": remote_url, "commit_id": COMMIT}}
        with self.captureOnCommitCallbacks(execute=False):
            release = create_release(self.team.id, version="1.0.0", project="shop", metadata=metadata)
        return str(release.id)

    def _gitlab_integration(self, hostname: str, path: str) -> None:
        Integration.objects.create(
            team=self.team,
            kind="gitlab",
            integration_id=path,
            config={"hostname": hostname, "path_with_namespace": path, "project_id": 42},
            sensitive_config={"access_token": "glpat-example-token"},
        )

    def _key(self, commit: str) -> str:
        return f"repo_paths/v1/{self.team.id}/gitlab.example.com/acme/shop/{commit}.zst"

    def test_writes_the_sorted_list_fetched_from_the_integration_host(self) -> None:
        self._gitlab_integration("https://gitlab.example.com:8443", "acme/shop")
        release_id = self._release("git@GitLab.example.com:acme/shop.git")

        result = store_release_file_list(self.team.id, release_id)

        assert result.outcome == "written"
        assert [target.remote.url for target in self.fetched] == ["https://gitlab.example.com:8443/acme/shop.git"]
        content, _ = self.storage.objects[self._key(COMMIT)]
        assert zstd.decompress(content).decode() == "\n".join(sorted(PATHS))
        assert result.provider == "gitlab"
        assert result.stored == StoredFileList(
            path_count=len(PATHS), stored_bytes=len(content), fetched_bytes=1, fetch_seconds=0.1, removed_lists=0
        )

    @override_settings(ERROR_TRACKING_REPO_PATHS_MAX_PATHS=2)
    def test_a_list_above_the_cap_writes_nothing(self) -> None:
        self._gitlab_integration("https://gitlab.example.com", "acme/shop")
        release_id = self._release("https://gitlab.example.com/acme/shop.git")

        assert store_release_file_list(self.team.id, release_id).outcome == "too_large"
        assert self.storage.objects == {}

    def test_a_refused_git_host_is_final_and_writes_nothing(self) -> None:
        self._gitlab_integration("https://gitlab.example.com", "acme/shop")
        release_id = self._release("https://gitlab.example.com/acme/shop.git")

        with patch(
            "products.error_tracking.backend.logic.repo_paths.release_files.list_repository_files",
            side_effect=GitHostNotAllowed("Disallowed target IP"),
        ):
            assert store_release_file_list(self.team.id, release_id).outcome == "host_not_allowed"
        assert self.storage.objects == {}

    @parameterized.expand([("new_list", False, "written"), ("list_stored_before_a_failed_cleanup", True, "exists")])
    def test_keeps_only_the_newest_lists_of_the_repo(self, _name: str, already_stored: bool, expected: str) -> None:
        self._gitlab_integration("https://gitlab.example.com", "acme/shop")
        for commit in OLDER_COMMITS:
            self.storage.put(self._key(commit), b"old")
        other_repo = f"repo_paths/v1/{self.team.id}/gitlab.example.com/acme/shop-web/{'3' * 40}.zst"
        self.storage.put(other_repo, b"other")
        if already_stored:
            self.storage.put(self._key(COMMIT), b"stored")
        release_id = self._release("https://gitlab.example.com/acme/shop.git")

        assert store_release_file_list(self.team.id, release_id).outcome == expected
        assert sorted(self.storage.objects) == sorted([self._key(OLDER_COMMITS[1]), self._key(COMMIT), other_repo])

    @parameterized.expand(
        [
            ("github_repo_without_integration", "https://github.com/acme/shop.git", "no_integration"),
            ("gitlab_host_without_integration", "https://gitlab.other.example.com/acme/shop.git", "no_integration"),
        ]
    )
    def test_fetches_nothing_without_a_matching_integration(self, _name: str, remote_url: str, expected: str) -> None:
        self._gitlab_integration("https://gitlab.example.com", "acme/shop")
        release_id = self._release(remote_url)

        assert store_release_file_list(self.team.id, release_id).outcome == expected
        assert self.fetched == []

    @parameterized.expand(
        [
            ("budget_spent", False, 502, "budget_exhausted"),
            ("server_error", True, 502, "retry"),
            ("permission_refused", True, 422, "auth_failed"),
        ]
    )
    def test_github_token_minting_waits_for_the_budget_and_retries_only_on_a_server_error(
        self, _name: str, budget_admits: bool, status_code: int, expected: str
    ) -> None:
        github = MagicMock(github_installation_id=7)
        github.mint_scoped_installation_token.side_effect = GitHubIntegrationError(
            "mint failed", status_code=status_code
        )
        release_id = self._release("https://github.com/acme/shop.git")

        with (
            patch(
                "products.error_tracking.backend.logic.repo_paths.release_files.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ),
            patch(
                "products.error_tracking.backend.logic.repo_paths.release_files.consume_git_fetch_budget",
                return_value=budget_admits,
            ),
        ):
            outcome: str
            try:
                outcome = store_release_file_list(self.team.id, release_id).outcome
            except RepoPathsRetryableError:
                outcome = "retry"

        assert outcome == expected
        assert github.mint_scoped_installation_token.call_count == int(budget_admits)
        assert self.fetched == []

    @parameterized.expand(
        [
            ("server_error", GitHubIntegrationError("check failed", status_code=503), "retry"),
            ("not_covered", False, "no_integration"),
        ]
    )
    def test_a_github_repository_check_retries_only_on_a_server_error(
        self, _name: str, check_result: bool | Exception, expected: str
    ) -> None:
        Integration.objects.create(
            team=self.team, kind="github", integration_id="7", sensitive_config={"access_token": "example-token"}
        )
        release_id = self._release("https://github.com/acme/shop.git")

        with patch.object(GitHubIntegration, "installation_can_access_repository_strict", side_effect=[check_result]):
            outcome: str
            try:
                outcome = store_release_file_list(self.team.id, release_id).outcome
            except RepoPathsRetryableError:
                outcome = "retry"

        assert outcome == expected
        assert self.fetched == []


class TestReleaseTrigger(BaseTest):
    @parameterized.expand(
        [
            ("full_commit", {"git": {"remote_url": "https://github.com/acme/shop.git", "commit_id": COMMIT}}, True),
            (
                "short_commit",
                {"git": {"remote_url": "https://github.com/acme/shop.git", "commit_id": "0123abc"}},
                False,
            ),
            ("no_remote", {"git": {"commit_id": COMMIT}}, False),
            ("no_git_metadata", {"version": "1.0.0"}, False),
        ]
    )
    def test_queues_the_job_after_commit_only_for_a_full_commit(
        self, _name: str, metadata: dict[str, object], queued: bool
    ) -> None:
        with patch("products.error_tracking.backend.tasks.tasks.start_error_tracking_repo_paths_job.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                release = create_release(self.team.id, version="1.0.0", project="shop", metadata=metadata)
                delay.assert_not_called()

        if queued:
            delay.assert_called_once_with(team_id=self.team.id, release_id=str(release.id))
        else:
            delay.assert_not_called()

    def test_queues_the_job_when_an_update_adds_git_metadata(self) -> None:
        release = create_release(self.team.id, version="1.0.0", project="shop", metadata={"version": "1.0.0"})
        metadata = {"git": {"remote_url": "https://github.com/acme/shop.git", "commit_id": COMMIT}}

        with patch("products.error_tracking.backend.tasks.tasks.start_error_tracking_repo_paths_job.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                update_release(self.team.id, str(release.id), metadata=metadata)

        delay.assert_called_once_with(team_id=self.team.id, release_id=str(release.id))
