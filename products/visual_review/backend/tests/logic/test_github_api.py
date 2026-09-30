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
