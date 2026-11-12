from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.visual_review.backend.logic import github_api
from products.visual_review.backend.models import Repo

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


class TestCompareCommits:
    @pytest.mark.parametrize(
        "total_commits,expected_requests,expected_complete",
        [
            (150, 2, True),
            (5000, github_api.MAX_COMPARE_COMMITS // 100, False),
        ],
    )
    def test_reads_every_page_up_to_the_cap(
        self, total_commits: int, expected_requests: int, expected_complete: bool
    ) -> None:
        def page(method, path, *, params, **kwargs):
            first = (params["page"] - 1) * params["per_page"]
            count = max(0, min(params["per_page"], total_commits - first))
            response = MagicMock(status_code=200)
            response.json.return_value = {
                "merge_base_commit": {"sha": "base"},
                "total_commits": total_commits,
                "commits": [
                    {"sha": f"c{first + i}", "parents": [{"sha": "p"}], "commit": {"message": "feat: x (#1)\n\nbody"}}
                    for i in range(count)
                ],
            }
            return response

        github = MagicMock()
        github.api_request.side_effect = page
        repo = Repo(repo_full_name="org/repo", repo_external_id=1)

        with patch.object(github_api, "get_github_integration_for_repo", return_value=github):
            comparison = github_api.compare_commits(repo, "base", "head")

        assert comparison is not None
        assert github.api_request.call_count == expected_requests
        assert comparison.complete is expected_complete
        assert len(comparison.commits) == min(total_commits, github_api.MAX_COMPARE_COMMITS)
        assert comparison.commits[0].subject == "feat: x (#1)"

    @pytest.mark.parametrize("head", ["../../pulls/1", "abc/./def"])
    def test_a_head_with_dot_segments_sends_no_request(self, head: str) -> None:
        github = MagicMock()
        repo = Repo(repo_full_name="org/repo", repo_external_id=1)

        with patch.object(github_api, "get_github_integration_for_repo", return_value=github):
            comparison = github_api.compare_commits(repo, "base", head)

        assert comparison is None
        github.api_request.assert_not_called()


@pytest.mark.parametrize(
    ("merged_at", "expected"),
    [("2026-10-01T12:00:00Z", datetime(2026, 10, 1, 12, tzinfo=UTC)), (None, None)],
)
def test_pull_request_state_reads_the_merge_time(merged_at: str | None, expected: datetime | None) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "state": "closed",
        "merged": merged_at is not None,
        "merged_at": merged_at,
        "base": {"ref": "release"},
        "head": {"sha": "head-7"},
    }
    github = MagicMock()
    github.api_request.return_value = response

    with patch.object(github_api, "get_github_integration_for_repo", return_value=github):
        state = github_api.pull_request_state(Repo(repo_full_name="org/repo"), 7)

    assert state is not None and state.merged_at == expected


@pytest.mark.parametrize(
    "refusal",
    [
        GitHubRateLimitError("rate limited", retry_after=42),
        GitHubEgressBudgetExhausted("shed", scope="1"),
    ],
)
def test_a_refused_ancestry_read_propagates_and_commit_contains_answers_false(refusal: Exception) -> None:
    github = MagicMock()
    github.api_request.side_effect = refusal
    repo = Repo(repo_full_name="org/repo")

    with patch.object(github_api, "get_github_integration_for_repo", return_value=github):
        with pytest.raises(type(refusal)):
            github_api.commit_ancestry(repo, "merge-base", "seed")
        assert github_api.commit_contains(repo, "merge-base", "seed") is False
