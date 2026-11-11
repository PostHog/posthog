import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.visual_review.backend.logic import github_api

_BIG_FILE = "version: 1\nsnapshots:\n  button--light:\n    hash: v1.k.abc.tag\n"


def _github(sha_by_ref: dict[str, str]) -> MagicMock:
    github = MagicMock()
    github.get_file_entry.side_effect = lambda repo, path, ref: {
        "sha": sha_by_ref[ref],
        "size": len(_BIG_FILE),
        "content": None,
    }
    github.get_blob_text.return_value = _BIG_FILE
    return github


class TestFetchBaselineFile:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()

    @pytest.mark.parametrize(
        "sha_by_ref,blob_reads",
        [
            ({"feature": "blob-1", "abc123": "blob-1"}, 1),
            ({"feature": "blob-1", "abc123": "blob-2"}, 2),
        ],
    )
    def test_a_blob_is_downloaded_once_per_sha(self, sha_by_ref: dict[str, str], blob_reads: int) -> None:
        github = _github(sha_by_ref)

        results = [github_api._fetch_baseline_file(github, "org/repo", "snapshots.yml", ref) for ref in sha_by_ref]

        assert github.get_blob_text.call_count == blob_reads
        assert [baseline for baseline, _sha in results] == [{"button--light": {"hash": "v1.k.abc.tag"}}] * 2
        assert [sha for _baseline, sha in results] == list(sha_by_ref.values())

    def test_an_unreachable_cache_still_reads_the_file(self) -> None:
        github = _github({"feature": "blob-1"})

        with patch("posthog.utils.cache") as broken_cache:
            broken_cache.get.side_effect = ConnectionError("cache down")
            broken_cache.set.side_effect = ConnectionError("cache down")
            baseline, sha = github_api._fetch_baseline_file(github, "org/repo", "snapshots.yml", "feature")

        assert baseline == {"button--light": {"hash": "v1.k.abc.tag"}}
        assert sha == "blob-1"

    def test_a_caller_editing_the_result_does_not_change_the_next_read(self) -> None:
        github = _github({"feature": "blob-1", "other": "blob-1"})

        first, _sha = github_api._fetch_baseline_file(github, "org/repo", "snapshots.yml", "feature")
        first.pop("button--light")
        second, _sha = github_api._fetch_baseline_file(github, "org/repo", "snapshots.yml", "other")

        assert second == {"button--light": {"hash": "v1.k.abc.tag"}}


def _commit(message: str) -> dict:
    return {"commit": {"message": message}}


def _merge(head: str) -> dict:
    return _commit(f"Merging {head} into trunk-temp/pr-1/abc\n\nbody")


class TestMergeQueueBatch:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()

    def _batch(self, responses: list[MagicMock]) -> github_api.MergeQueueBatch | None:
        github = MagicMock()
        github.api_request.side_effect = responses
        repo = MagicMock(id="repo-1", repo_full_name="org/repo")
        with (
            patch.object(github_api, "default_branch_name", return_value="master"),
            patch.object(github_api, "get_github_integration_for_repo", return_value=github),
        ):
            return github_api.merge_queue_batch(repo, "f" * 40)

    def _page(self, commits: list[dict], status: int = 200) -> MagicMock:
        return MagicMock(status_code=status, json=lambda: {"merge_base_commit": {"sha": "base"}, "commits": commits})

    def test_collects_the_stacked_merge_commits_across_pages(self) -> None:
        first_page = [_merge("1" * 40), *[_commit("Fix a typo") for _ in range(98)], _merge("2" * 40)]
        second_page = [_commit("Merge branch 'master'"), _merge("3" * 40)]

        batch = self._batch([self._page(first_page), self._page(second_page)])

        assert batch == github_api.MergeQueueBatch(
            base_sha="base", pull_request_heads=frozenset({"1" * 40, "2" * 40, "3" * 40})
        )

    @pytest.mark.parametrize(
        "commits,status",
        [([_merge("1" * 40)], 404), ([_commit("Fix a typo"), _commit("Merging feature into main")], 200)],
    )
    def test_is_unknown_when_github_fails_or_the_branch_merged_no_pull_request(
        self, commits: list[dict], status: int
    ) -> None:
        assert self._batch([self._page(commits, status)]) is None
