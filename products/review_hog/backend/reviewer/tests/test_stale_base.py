from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.review_hog.backend.reviewer.stale_base import (
    StaleBaseChecker,
    StaleBaseDecision,
    commit_subjects,
    is_pr_stale_for_publish,
)
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError

_MODULE = "products.review_hog.backend.reviewer.stale_base"


def _commit(sha: str, message: str, *, merge: bool = False) -> dict[str, Any]:
    return {
        "sha": sha,
        "parents": [{"sha": "p1"}, {"sha": "p2"}] if merge else [{"sha": "p1"}],
        "commit": {"message": message},
    }


def _compare(
    *,
    merge_base_sha: str | None = None,
    ahead_by: int = 0,
    behind_by: int = 0,
    commits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"ahead_by": ahead_by, "behind_by": behind_by}
    if merge_base_sha is not None:
        payload["merge_base_commit"] = {"sha": merge_base_sha}
    if commits is not None:
        payload["commits"] = commits
    return payload


def _github(responses: dict[str, dict[str, Any] | Exception]):
    calls: list[str] = []

    def request(method: str, path: str, **kwargs: Any) -> MagicMock:
        rel = path.removeprefix("/repos/PostHog/posthog/")
        calls.append(rel)
        response = responses[rel]
        if isinstance(response, Exception):
            raise response
        return MagicMock(json=MagicMock(return_value=response))

    return request, calls


def _check(
    responses: dict[str, dict[str, Any] | Exception],
    *,
    default_branch: str | None = "master",
    base_branch: str | None = "layer-1",
    head_sha: str | None = "head-sha",
    base_sha: str | None = "base-sha",
    merge_base_sha: str | None = None,
    base_behind_by: int | None = None,
) -> tuple[StaleBaseDecision, list[str]]:
    checker = StaleBaseChecker(repository="PostHog/posthog", token="tok", installation_id="9")
    side_effect, calls = _github(responses)
    with patch(f"{_MODULE}.github_api_request", side_effect=side_effect):
        decision = checker.check(
            default_branch=default_branch,
            base_branch=base_branch,
            head_sha=head_sha,
            base_sha=base_sha,
            merge_base_sha=merge_base_sha,
            base_behind_by=base_behind_by,
        )
    return decision, calls


class TestStaleBaseChecker:
    @parameterized.expand(
        [
            ("targets_default_branch", "master", "master", "head-sha"),
            ("missing_default_branch", None, "layer-1", "head-sha"),
            ("missing_base_branch", "master", None, "head-sha"),
            ("missing_head_sha", "master", "layer-1", None),
        ]
    )
    def test_default_base_or_missing_refs_makes_zero_api_calls(
        self,
        _name: str,
        default_branch: str | None,
        base_branch: str | None,
        head_sha: str | None,
    ) -> None:
        decision, calls = _check(
            {},
            default_branch=default_branch,
            base_branch=base_branch,
            head_sha=head_sha,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="default_base")
        assert calls == []

    def test_clean_stacked_pr_returns_clean_stack(self) -> None:
        # master(m1) -> layer-1(b1) -> layer-2(head-sha).
        # M_head = m1; m1 is an ancestor of b1 (ahead_by=0); merge_base(b1, head) = b1 != m1.
        decision, calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/base-sha...m1": _compare(ahead_by=0, behind_by=1),
            },
            merge_base_sha="b1",
            base_behind_by=0,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="clean_stack")
        assert calls == ["compare/master...head-sha", "compare/base-sha...m1"]

    def test_stacked_pr_with_fast_forwarded_base_stays_clean(self) -> None:
        # layer-1 gained a new commit b2 (behind_by=1), while head still branches cleanly off b1 (!= m1).
        decision, calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/base-sha...m1": _compare(ahead_by=0, behind_by=2),
            },
            merge_base_sha="b1",
            base_behind_by=1,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="clean_stack")
        assert len(calls) == 2

    def test_master_contaminated_stack_detected_as_base_behind_default(self) -> None:
        # head was rebased onto newer master m3 while layer-1 still sits on m1 (2 master commits leak into diff).
        decision, _calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m3"),
                "compare/base-sha...m3": _compare(ahead_by=2, behind_by=1),
            },
            merge_base_sha="m1",
            base_behind_by=1,
        )
        assert decision == StaleBaseDecision(
            stale=True,
            skip=True,
            reason="base_behind_default",
            default_commits_in_diff=2,
        )

    def test_rewritten_base_stack_detected_when_commit_subjects_overlap(self) -> None:
        # layer-1 was force-pushed/rebased (b1 -> b1'), while head still sits on old b1 -> h1.
        # Both diverge at master m1, behind_by > 0, and base's rewritten commit subject appears in base...head.
        decision, _calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/base-sha...m1": _compare(ahead_by=0, behind_by=1),
                "compare/base-sha...head-sha": _compare(
                    merge_base_sha="m1",
                    behind_by=1,
                    commits=[
                        _commit("b1_old", "feat(metrics): add derived series backend support"),
                        _commit("h1", "feat(metrics): wire derived series UI picker"),
                    ],
                ),
                "compare/master...base-sha": _compare(
                    commits=[_commit("b1_new", "feat(metrics): add derived series backend support\n\nDetails...")]
                ),
            },
            merge_base_sha="m1",
            base_behind_by=1,
        )
        assert decision == StaleBaseDecision(
            stale=True,
            skip=True,
            reason="base_rewritten",
            overlapping_base_commits=1,
        )

    def test_independent_pr_targeting_release_branch_is_not_flagged_as_rewritten(self) -> None:
        # PR branched off master targeting long-lived release/v2 (behind_by > 0, MB == m1) with distinct commits.
        decision, _calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/base-sha...m1": _compare(ahead_by=0, behind_by=3),
                "compare/base-sha...head-sha": _compare(
                    merge_base_sha="m1",
                    behind_by=3,
                    commits=[_commit("h1", "fix(billing): handle empty invoice period gracefully")],
                ),
                "compare/master...base-sha": _compare(
                    commits=[
                        _commit("r1", "chore(release): prepare v2 release branch"),
                        _commit("r2", "fix"),  # trivial subject ignored
                        _commit("r3", "Merge branch 'master' into release/v2", merge=True),
                    ]
                ),
            },
            base_branch="release/v2",
            merge_base_sha="m1",
            base_behind_by=3,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="clean_stack")

    def test_trivial_or_merge_commit_subjects_never_trigger_rewritten_base(self) -> None:
        # Both branches happen to have a trivial "fix" commit and a merge commit; must NOT trigger base_rewritten.
        decision, _calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/base-sha...m1": _compare(ahead_by=0, behind_by=2),
                "compare/base-sha...head-sha": _compare(
                    merge_base_sha="m1",
                    behind_by=2,
                    commits=[
                        _commit("h1", "fix"),
                        _commit("h2", "wip"),
                        _commit("h3", "Merge branch 'master' into feat", merge=True),
                    ],
                ),
                "compare/master...base-sha": _compare(
                    commits=[
                        _commit("b1", "fix"),
                        _commit("b2", "wip"),
                        _commit("b3", "Merge branch 'master' into feat", merge=True),
                    ]
                ),
            },
            merge_base_sha="m1",
            base_behind_by=2,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="clean_stack")

    def test_falls_back_to_base_branch_when_base_sha_absent_and_fetches_base_compare_if_missing(self) -> None:
        decision, calls = _check(
            {
                "compare/master...head-sha": _compare(merge_base_sha="m1"),
                "compare/layer-1...m1": _compare(ahead_by=0, behind_by=1),
                "compare/layer-1...head-sha": _compare(merge_base_sha="b1", behind_by=0),
            },
            base_sha=None,
            merge_base_sha=None,
            base_behind_by=None,
        )
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="clean_stack")
        assert calls == ["compare/master...head-sha", "compare/layer-1...m1", "compare/layer-1...head-sha"]

    @parameterized.expand(
        [
            ("github_api_error", GitHubAPIError("not found", status=404)),
            ("network_error", requests.ConnectionError("timeout")),
        ]
    )
    def test_github_errors_fail_open(self, _name: str, error: Exception) -> None:
        decision, _calls = _check({"compare/master...head-sha": error})
        assert decision == StaleBaseDecision(stale=False, skip=False, reason="unavailable")

    def test_shadow_mode_records_stale_without_skipping(self) -> None:
        with patch(f"{_MODULE}.SKIP_STALE_BASE", False):
            decision, _calls = _check(
                {
                    "compare/master...head-sha": _compare(merge_base_sha="m3"),
                    "compare/base-sha...m3": _compare(ahead_by=4),
                },
                merge_base_sha="m1",
                base_behind_by=1,
            )
        assert decision == StaleBaseDecision(
            stale=True,
            skip=False,
            reason="base_behind_default",
            default_commits_in_diff=4,
        )


class TestCommitSubjects:
    def test_normalizes_and_filters_subjects(self) -> None:
        commits = [
            _commit("1", "  Feat(ReviewHog):  add stale-base guard  \n\nLong body"),
            _commit("2", "wip"),
            _commit("3", "short msg"),
            _commit("4", "Merge pull request #123 from PostHog/foo", merge=True),
            _commit("5", "Merge branch 'master' into feature"),
        ]
        assert commit_subjects(commits) == {"feat(reviewhog): add stale-base guard"}


class TestIsPrStaleForPublish:
    @parameterized.expand(
        [
            ("open_same_base", "open", "layer-1", "layer-1", None),
            ("unknown_live_values_fail_open", None, None, "layer-1", None),
            ("closed_pr", "closed", "layer-1", "layer-1", "pr_not_open"),
            ("base_retargeted_to_master", "open", "master", "layer-1", "base_branch_changed"),
            ("base_retargeted_to_new_parent", "open", "layer-0", "layer-1", "base_branch_changed"),
        ]
    )
    def test_publish_staleness(
        self,
        _name: str,
        live_state: str | None,
        live_base: str | None,
        reviewed_base: str | None,
        expected: str | None,
    ) -> None:
        assert (
            is_pr_stale_for_publish(
                live_state=live_state,
                live_base_branch=live_base,
                reviewed_base_branch=reviewed_base,
            )
            == expected
        )
