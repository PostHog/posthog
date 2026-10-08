from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult

from products.review_hog.backend.reviewer.push_gate import PUSH_GATE_MODEL, PushGate, PushGateDecision
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError

_MODULE = "products.review_hog.backend.reviewer.push_gate"
_BILLING = "@@ -10,1 +10,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_AFTER_MERGE = "@@ -40,1 +40,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_FIX = "@@ -10,1 +10,1 @@\n-    return amount * 100\n+    return round(amount * 100)"


def _file(filename: str, patch: str | None = "@@ -1 +1 @@\n-a\n+b") -> dict[str, Any]:
    return {"filename": filename, "changes": 2, "patch": patch}


def _commit(sha: str, *, merge: bool = False) -> dict[str, Any]:
    return {"sha": sha, "parents": [{"sha": "p1"}, {"sha": "p2"}] if merge else [{"sha": "p1"}]}


def _pr(commits: list[dict[str, Any]], files: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_commits": len(commits), "commits": commits, "files": files}


def _push(
    *,
    new_commits: list[dict[str, Any]],
    pr_files: list[dict[str, Any]],
    own_commit_files: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any] | None]:
    return {
        "compare/master...old": _pr([_commit("a")], [_file("posthog/billing.py", _BILLING)]),
        "compare/master...new": _pr(new_commits, pr_files),
        "commits/c": {"files": own_commit_files or []},
    }


def _github(responses: dict[str, dict[str, Any] | None]):
    def request(method: str, path: str, **kwargs: Any) -> MagicMock:
        response = responses[path.removeprefix("/repos/PostHog/posthog/")]
        if response is None:
            raise GitHubAPIError("gone", status=404)
        return MagicMock(json=MagicMock(return_value=response))

    return request


def _decide(responses: dict[str, dict[str, Any] | None], system_one: MagicMock | None = None) -> PushGateDecision:
    with (
        patch(f"{_MODULE}.github_api_request", side_effect=_github(responses)),
        patch(f"{_MODULE}.build_system_one_client", MagicMock(return_value=system_one or MagicMock())),
    ):
        return PushGate(team_id=1, repository="PostHog/posthog", token="t", installation_id="9").decide(
            previous_head_sha="old", head_sha="new", base_branch="master"
        )


def _system_one(probability: float) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(
        model=PUSH_GATE_MODEL, answers={"alters": NoulAnswer(probability=probability)}, input_tokens=10
    )
    return client


_CODE_PUSH = _push(
    new_commits=[_commit("a"), _commit("c")],
    pr_files=[_file("posthog/billing.py", _BILLING_FIX), _file("README.md")],
    own_commit_files=[_file("posthog/billing.py", _BILLING_FIX), _file("README.md")],
)


@parameterized.expand(
    [
        (
            "force_push_back",
            _push(new_commits=[_commit("a")], pr_files=[_file("posthog/billing.py", _BILLING)]),
            "no_new_commits",
            True,
        ),
        # Master's commits are on the base, so only the merge commit is new, and the PR's lines only moved.
        (
            "base_merge",
            _push(
                new_commits=[_commit("a"), _commit("m", merge=True)],
                pr_files=[_file("posthog/billing.py", _BILLING_AFTER_MERGE)],
            ),
            "merge_only",
            True,
        ),
        (
            "rebase",
            _push(new_commits=[_commit("a2")], pr_files=[_file("posthog/billing.py", _BILLING_AFTER_MERGE)]),
            "merge_only",
            True,
        ),
        # ReviewHog never reviews lockfiles, yet a lockfile bump is the author's own change, not a merge.
        (
            "lockfile_bump",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING), _file("pnpm-lock.yaml")],
                own_commit_files=[_file("pnpm-lock.yaml")],
            ),
            "docs_only",
            False,
        ),
        (
            "docs_and_generated_files",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING), _file("README.md")],
                own_commit_files=[_file("README.md"), _file("frontend/src/generated/core/api.ts")],
            ),
            "docs_only",
            False,
        ),
    ]
)
def test_push_gate_matches_pushes_without_own_code_changes(
    _name: str, responses: dict[str, dict[str, Any] | None], reason: str, skip: bool
) -> None:
    system_one = _system_one(0.99)
    decision = _decide(responses, system_one)
    assert (decision.would_skip, decision.skip, decision.reason) == (True, skip, reason)
    system_one.decide.assert_not_called()


@parameterized.expand(
    [
        ("likely_behavior_change_runs", 0.8, False, False, False, "system_one_above_threshold"),
        ("shadow_skip_while_switched_off", 0.2, False, True, False, "system_one_below_threshold"),
        ("skip_once_switched_on", 0.2, True, True, True, "system_one_below_threshold"),
    ]
)
def test_push_gate_asks_system_one_about_own_code_commits(
    _name: str, probability: float, enabled: bool, would_skip: bool, skip: bool, reason: str
) -> None:
    system_one = _system_one(probability)
    with patch(f"{_MODULE}.SKIP_SYSTEM_ONE", enabled):
        decision = _decide(_CODE_PUSH, system_one)
    assert (decision.would_skip, decision.skip, decision.reason, decision.probability, decision.model) == (
        would_skip,
        skip,
        reason,
        probability,
        PUSH_GATE_MODEL,
    )
    call = system_one.decide.call_args.kwargs
    # The threshold was calibrated on exactly this state: own code patches, docs dropped.
    assert call["state"] == f"--- posthog/billing.py\n{_BILLING_FIX}"
    assert "round" not in str(call["questions"]["alters"].instructions)


@parameterized.expand(
    [
        ("not_configured", SystemOneNotConfigured("no gateway")),
        ("request_failed", SystemOneRequestFailed("HTTP 500", status_code=500)),
    ]
)
def test_push_gate_reviews_the_push_when_system_one_is_unavailable(_name: str, error: Exception) -> None:
    system_one = MagicMock()
    system_one.decide.side_effect = error
    with patch(f"{_MODULE}.SKIP_SYSTEM_ONE", True):
        decision = _decide(_CODE_PUSH, system_one)
    assert (decision.skip, decision.would_skip, decision.reason) == (False, False, "system_one_unavailable")


@parameterized.expand(
    [
        (
            "merge_resolves_conflict",
            _push(
                new_commits=[_commit("a"), _commit("m", merge=True)],
                pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
            ),
            "interdiff_too_large",
        ),
        ("compare_gone", {**_CODE_PUSH, "compare/master...new": None}, "compare_unavailable"),
        (
            "force_push_drops_commit",
            {
                "compare/master...old": _pr([_commit("a"), _commit("c")], [_file("posthog/billing.py", _BILLING_FIX)]),
                "compare/master...new": _pr([_commit("a")], [_file("posthog/billing.py", _BILLING)]),
            },
            "commits_removed",
        ),
        (
            "patch_left_out",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", None)],
                own_commit_files=[_file("posthog/billing.py", None)],
            ),
            "interdiff_too_large",
        ),
    ]
)
def test_push_gate_reviews_a_push_it_cannot_see(
    _name: str, responses: dict[str, dict[str, Any] | None], reason: str
) -> None:
    system_one = _system_one(0.0)
    with patch(f"{_MODULE}.SKIP_SYSTEM_ONE", True):
        decision = _decide(responses, system_one)
    assert (decision.skip, decision.reason) == (False, reason)
    system_one.decide.assert_not_called()
