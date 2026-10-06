import base64
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult

from products.review_hog.backend.reviewer.push_gate import PUSH_GATE_MODEL, PushGate, PushGateDecision
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError

_MODULE = "products.review_hog.backend.reviewer.push_gate"
_GITATTRIBUTES = "frontend/src/generated/** linguist-generated\n*.pb.go linguist-generated\n"
_BILLING = "@@ -10,1 +10,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_AFTER_MERGE = "@@ -40,1 +40,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_FIX = "@@ -10,1 +10,1 @@\n-    return amount * 100\n+    return round(amount * 100)"


def _file(filename: str, patch: str | None = "@@ -1 +1 @@\n-a\n+b") -> dict[str, Any]:
    return {"filename": filename, "status": "modified", "changes": 2, "patch": patch}


def _github(compares: dict[str, dict[str, Any] | None]):
    def request(method: str, path: str, **kwargs: Any) -> MagicMock:
        if "/compare/" in path:
            comparison = compares[path.split("/compare/")[1]]
            if comparison is None:
                raise GitHubAPIError("gone", status=404)
            return MagicMock(json=MagicMock(return_value=comparison))
        assert path.endswith("/contents/.gitattributes")
        return MagicMock(json=MagicMock(return_value={"content": base64.b64encode(_GITATTRIBUTES.encode()).decode()}))

    return request


def _push(
    *, interdiff: list[dict[str, Any]], pr_after: list[dict[str, Any]], ahead_by: int = 1
) -> dict[str, dict[str, Any] | None]:
    return {
        "old...new": {"ahead_by": ahead_by, "files": interdiff},
        "master...old": {"ahead_by": 1, "files": [_file("posthog/billing.py", _BILLING)]},
        "master...new": {"ahead_by": 2, "files": pr_after},
    }


def _decide(compares: dict[str, dict[str, Any] | None], system_one: MagicMock | None = None) -> PushGateDecision:
    with (
        patch(f"{_MODULE}.github_api_request", side_effect=_github(compares)),
        patch(f"{_MODULE}.build_system_one_client", MagicMock(return_value=system_one or MagicMock())),
    ):
        return PushGate(team_id=1, repository="PostHog/posthog", token="t", installation_id="9").decide(
            previous_head_sha="old", head_sha="new", base_branch="master"
        )


def _system_one(probability: float) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = SystemOneResult(
        model=PUSH_GATE_MODEL, answers={"behavior_change": NoulAnswer(probability=probability)}, input_tokens=10
    )
    return client


_CODE_PUSH = _push(
    interdiff=[_file("posthog/billing.py", _BILLING_FIX), _file("products/x/skills/a/SKILL.md")],
    pr_after=[_file("posthog/billing.py", _BILLING_FIX), _file("products/x/skills/a/SKILL.md")],
)


@parameterized.expand(
    [
        ("force_push_back", _push(interdiff=[], pr_after=[], ahead_by=0), "no_new_commits", True),
        # The author merged master: base files changed, and the PR's own lines only moved down.
        (
            "base_merge",
            _push(
                interdiff=[_file("posthog/other.py"), _file("posthog/billing.py", "@@ -1 +1 @@\n-x\n+y")],
                pr_after=[_file("posthog/billing.py", _BILLING_AFTER_MERGE)],
            ),
            "merge_only",
            True,
        ),
        # ReviewHog never reviews lockfiles, yet a lockfile bump is the author's own change, not a merge.
        (
            "lockfile_bump",
            _push(
                interdiff=[_file("pnpm-lock.yaml")],
                pr_after=[_file("posthog/billing.py", _BILLING), _file("pnpm-lock.yaml")],
            ),
            "docs_only",
            False,
        ),
        (
            "docs_and_generated_files",
            _push(
                interdiff=[_file("README.md"), _file("frontend/src/generated/core/api.ts"), _file("rust/x.pb.go")],
                pr_after=[
                    _file("posthog/billing.py", _BILLING),
                    _file("README.md"),
                    _file("frontend/src/generated/core/api.ts"),
                    _file("rust/x.pb.go"),
                ],
            ),
            "docs_only",
            False,
        ),
    ]
)
def test_push_gate_matches_pushes_without_own_code_changes(
    _name: str, compares: dict[str, dict[str, Any] | None], reason: str, skip: bool
) -> None:
    system_one = _system_one(0.99)
    decision = _decide(compares, system_one)
    assert (decision.would_skip, decision.skip, decision.reason) == (True, skip, reason)
    system_one.decide.assert_not_called()


@parameterized.expand(
    [
        ("likely_behavior_change_runs", 0.8, False, False, False, "system_one_above_threshold"),
        ("shadow_skip_while_switched_off", 0.02, False, True, False, "system_one_below_threshold"),
        ("skip_once_switched_on", 0.02, True, True, True, "system_one_below_threshold"),
    ]
)
def test_push_gate_asks_system_one_about_a_code_change(
    _name: str, probability: float, enabled: bool, would_skip: bool, skip: bool, reason: str
) -> None:
    system_one = _system_one(probability)
    with patch(f"{_MODULE}.SKIP_SYSTEM_ONE", enabled):
        decision = _decide(_CODE_PUSH, system_one)
    assert (decision.would_skip, decision.skip, decision.reason, decision.probability) == (
        would_skip,
        skip,
        reason,
        probability,
    )
    state = system_one.decide.call_args.kwargs["state"]
    question = system_one.decide.call_args.kwargs["questions"]["behavior_change"]
    # Markdown in a skills directory is runtime input, so it goes to System One like code.
    assert _BILLING_FIX in state["interdiff"] and "SKILL.md" in state["interdiff"]
    assert "round" not in str(question.instructions)


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
        ("compare_gone", {**_CODE_PUSH, "old...new": None}, "compare_unavailable"),
        (
            "patch_left_out",
            _push(interdiff=[_file("posthog/billing.py", None)], pr_after=[_file("posthog/billing.py", None)]),
            "interdiff_too_large",
        ),
    ]
)
def test_push_gate_reviews_a_push_it_cannot_see(
    _name: str, compares: dict[str, dict[str, Any] | None], reason: str
) -> None:
    system_one = _system_one(0.0)
    with patch(f"{_MODULE}.SKIP_SYSTEM_ONE", True):
        decision = _decide(compares, system_one)
    assert (decision.skip, decision.reason) == (False, reason)
    system_one.decide.assert_not_called()
