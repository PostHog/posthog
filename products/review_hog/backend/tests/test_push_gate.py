from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from temporalio.converter import DataConverter

from posthog.redis import TEST_clear_clients, get_client
from posthog.token_bucket import BucketUnavailable, TEST_reset_scripts

from products.review_hog.backend.reviewer.artefact_content import PRSnapshotArtefact
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate, PRMetadata
from products.review_hog.backend.reviewer.push_gate import (
    PRChange,
    PushGate,
    PushGateDecision,
    apply_draft_rule,
    apply_follow_up_value_rules,
    apply_throttle,
    apply_zero_change_rule,
    plan_delta_review,
)
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError

_MODULE = "products.review_hog.backend.reviewer.push_gate"
_BILLING = "@@ -10,1 +10,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_AFTER_MERGE = "@@ -40,1 +40,1 @@\n-    return amount\n+    return amount * 100"
_BILLING_FIX = "@@ -10,1 +10,1 @@\n-    return amount * 100\n+    return round(amount * 100)"


def _file(filename: str, patch: str | None = "@@ -1 +1 @@\n-a\n+b") -> dict[str, Any]:
    return {"filename": filename, "changes": 2, "patch": patch}


_REVIEWHOG_BOT = {"login": "reviewhog[bot]", "type": "Bot"}


def _commit(
    sha: str,
    *,
    merge: bool = False,
    author: dict[str, str] | None = None,
    committer: dict[str, str] | None = None,
    verified: bool = False,
) -> dict[str, Any]:
    return {
        "sha": sha,
        "parents": [{"sha": "p1"}, {"sha": "p2"}] if merge else [{"sha": "p1"}],
        "author": author or {"login": "octocat", "type": "User"},
        "committer": committer or author or {"login": "octocat", "type": "User"},
        "commit": {"verification": {"verified": verified}},
    }


def _own_commit(sha: str) -> dict[str, Any]:
    return _commit(sha, author=_REVIEWHOG_BOT, committer=_REVIEWHOG_BOT, verified=True)


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


def _decide(responses: dict[str, dict[str, Any] | None], *, draft: bool = False) -> PushGateDecision:
    gate = PushGate(repository="PostHog/posthog", token="t", installation_id="9")
    with (
        patch(f"{_MODULE}.github_api_request", side_effect=_github(responses)),
        patch(f"{_MODULE}.posthog_app_login", return_value="reviewhog[bot]"),
    ):
        decision = gate.decide(previous_head_sha="old", head_sha="new", base_branch="master")
    return apply_draft_rule(decision, draft=draft)


_CODE_PUSH = _push(
    new_commits=[_commit("a"), _commit("c")],
    pr_files=[_file("posthog/billing.py", _BILLING_FIX), _file("README.md")],
    own_commit_files=[_file("posthog/billing.py", _BILLING_FIX), _file("README.md")],
)
_DOCS_PUSH = _push(
    new_commits=[_commit("a"), _commit("c")],
    pr_files=[_file("posthog/billing.py", _BILLING), _file("README.md")],
    own_commit_files=[_file("README.md")],
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
        # The resolution stage pushed fixes for the last review's findings.
        (
            "reviewhog_fix_commits",
            _push(
                new_commits=[_commit("a"), _own_commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
                own_commit_files=[_file("posthog/billing.py", _BILLING_FIX)],
            ),
            "reviewhog_commits_only",
            True,
        ),
    ]
)
def test_push_gate_skips_pushes_without_new_own_changes(
    _name: str, responses: dict[str, dict[str, Any] | None], reason: str, skip: bool
) -> None:
    decision = _decide(responses)
    assert (decision.would_skip, decision.skip, decision.reason) == (True, skip, reason)


@parameterized.expand(
    [
        ("code_push", _CODE_PUSH, 2),
        ("docs_push", _DOCS_PUSH, 0),
        # ReviewHog never reviews lockfiles, yet a lockfile bump is the author's own change, not a merge.
        (
            "lockfile_bump",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING), _file("pnpm-lock.yaml")],
                own_commit_files=[_file("pnpm-lock.yaml")],
            ),
            0,
        ),
    ]
)
def test_push_gate_reviews_own_changes_and_counts_only_code_lines(
    _name: str, responses: dict[str, dict[str, Any] | None], own_code_lines: int
) -> None:
    decision = _decide(responses)
    assert (decision.would_skip, decision.skip, decision.reason, decision.own_code_lines) == (
        False,
        False,
        "no_rule_matched",
        own_code_lines,
    )


def test_push_gate_logs_no_push_size_when_a_commit_lists_a_full_page_of_files() -> None:
    full_page = [_file(f"posthog/module_{n}.py") for n in range(300)]
    push = _push(
        new_commits=[_commit("a"), _commit("c")],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
        own_commit_files=full_page,
    )
    decision = _decide(push)
    assert (decision.reason, decision.own_code_lines) == ("no_rule_matched", None)


def test_push_gate_reviews_a_push_that_mixes_reviewhog_and_author_commits() -> None:
    push = _push(
        new_commits=[_commit("a"), _own_commit("r"), _commit("c")],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
        own_commit_files=[_file("posthog/billing.py", _BILLING_FIX)],
    )
    decision = _decide({**push, "commits/r": {"files": []}})
    assert (decision.skip, decision.reason) == (False, "no_rule_matched")


@parameterized.expand(
    [
        ("unsigned", _commit("s", author=_REVIEWHOG_BOT)),
        (
            "signed_by_a_person",
            _commit("s", author=_REVIEWHOG_BOT, committer={"login": "mallory", "type": "User"}, verified=True),
        ),
    ]
)
def test_push_gate_reviews_commits_that_only_claim_the_app_as_author(_name: str, spoofed: dict[str, Any]) -> None:
    push = _push(
        new_commits=[_commit("a"), spoofed],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
    )
    decision = _decide({**push, "commits/s": {"files": [_file("posthog/billing.py", _BILLING_FIX)]}})
    assert decision.reason != "reviewhog_commits_only"


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
    decision = _decide(responses)
    assert (decision.skip, decision.reason) == (False, reason)


@parameterized.expand(
    [
        ("code_push", _CODE_PUSH, (True, True, "draft", 2)),
        ("docs_push", _DOCS_PUSH, (True, True, "draft", 0)),
        # A rule that skips on its own is more specific than the draft state.
        (
            "force_push_back",
            _push(new_commits=[_commit("a")], pr_files=[_file("posthog/billing.py", _BILLING)]),
            (True, True, "no_new_commits", None),
        ),
    ]
)
def test_push_gate_skips_a_draft_push_and_keeps_the_push_size(
    _name: str, responses: dict[str, dict[str, Any] | None], expected: tuple[bool, bool, str, int | None]
) -> None:
    decision = _decide(responses, draft=True)
    assert (decision.skip, decision.would_skip, decision.reason, decision.own_code_lines) == expected


@pytest.fixture
def empty_redis() -> Iterator[None]:
    TEST_clear_clients()
    TEST_reset_scripts()
    # The fake Redis server outlives its clients, so a counter from an earlier test would stay.
    get_client().flushdb()
    yield
    TEST_clear_clients()
    TEST_reset_scripts()


def test_push_gate_throttles_the_third_push_in_half_an_hour(empty_redis: None) -> None:
    reviewed = PushGateDecision(skip=False, would_skip=False, reason="no_rule_matched")
    draft = PushGateDecision(skip=True, would_skip=True, reason="draft")
    pushes = [
        # A push that an earlier rule skips takes no token.
        (0, "pr-a", "a1", draft),
        (0, "pr-a", "a2", reviewed),
        (1, "pr-a", "a3", reviewed),
        # A retried turn at a head that paid already runs without a second token.
        (2, "pr-a", "a3", reviewed),
        (2, "pr-b", "b1", reviewed),
        (3, "pr-a", "a4", reviewed),
        # A retry after a denial asks the bucket again.
        (4, "pr-a", "a4", reviewed),
        # One token comes back 30 minutes after the first one went.
        (31, "pr-a", "a5", reviewed),
        (32, "pr-a", "a6", reviewed),
    ]
    start = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    outcomes = []
    with time_machine.travel(start, tick=False) as clock:
        for minutes, report_id, head_sha, decision in pushes:
            clock.move_to(start + timedelta(minutes=minutes))
            result = apply_throttle(decision, report_id=report_id, head_sha=head_sha)
            outcomes.append((result.skip, result.reason))

    assert outcomes == [
        (True, "draft"),
        (False, "no_rule_matched"),
        (False, "no_rule_matched"),
        (False, "no_rule_matched"),
        (False, "no_rule_matched"),
        (True, "throttled"),
        (True, "throttled"),
        (False, "no_rule_matched"),
        (True, "throttled"),
    ]


def test_push_gate_reviews_the_push_when_redis_is_down(empty_redis: None) -> None:
    reviewed = PushGateDecision(skip=False, would_skip=False, reason="no_rule_matched")
    with patch(f"{_MODULE}.consume", return_value=BucketUnavailable(error="down")):
        assert apply_throttle(reviewed, report_id="pr-a", head_sha="a1") == reviewed


def _running(own_code_lines: int | None) -> PushGateDecision:
    return PushGateDecision(skip=False, would_skip=False, reason="no_rule_matched", own_code_lines=own_code_lines)


@parameterized.expand(
    [
        ("ninth_review", _running(200), 9, 2000, 3, (True, True, "late_follow_up")),
        ("eighth_review_runs", _running(200), 8, 2000, 3, (False, False, "no_rule_matched")),
        ("pr_under_150_lines", _running(200), 3, 149, 3, (True, True, "small_pr")),
        ("pr_of_150_lines_runs", _running(200), 3, 150, 3, (False, False, "no_rule_matched")),
        ("quiet_review_and_small_push", _running(30), 3, 400, 0, (True, True, "quiet_small_push")),
        ("quiet_review_and_larger_push_runs", _running(31), 3, 400, 0, (False, False, "no_rule_matched")),
        ("review_with_a_finding_runs", _running(5), 3, 400, 1, (False, False, "no_rule_matched")),
        ("unknown_inputs_run", _running(None), 3, None, None, (False, False, "no_rule_matched")),
        (
            "gate_failure_keeps_running",
            PushGateDecision(skip=False, would_skip=False, reason="compare_unavailable"),
            12,
            50,
            0,
            (False, False, "compare_unavailable"),
        ),
        (
            "earlier_skip_keeps_its_reason",
            PushGateDecision(skip=True, would_skip=True, reason="merge_only"),
            12,
            50,
            0,
            (True, True, "merge_only"),
        ),
    ]
)
def test_push_gate_skips_follow_ups_that_rarely_surface_anything(
    _name: str,
    decision: PushGateDecision,
    run_index: int,
    reviewable_lines: int | None,
    previous_findings: int | None,
    expected: tuple[bool, bool, str],
) -> None:
    result = apply_follow_up_value_rules(
        decision, run_index=run_index, reviewable_lines=reviewable_lines, previous_findings=previous_findings
    )
    assert (result.skip, result.would_skip, result.reason) == expected


def _change(**overrides: Any) -> PRChange:
    fields: dict[str, Any] = {
        "changed_lines": 12,
        "changed_reviewable_lines": 12,
        "dependency_changed": False,
        "comparable": True,
        **overrides,
    }
    return PRChange(**fields)


@parameterized.expand(
    [
        (
            "no_change_in_the_treatment_arm_skips",
            _running(0),
            _change(changed_lines=0),
            True,
            (True, True, "zero_change"),
        ),
        (
            "no_change_in_the_control_arm_runs_and_records_it",
            _running(0),
            _change(changed_lines=0),
            False,
            (False, True, "zero_change"),
        ),
        (
            "a_changed_line_runs",
            _running(0),
            _change(changed_lines=1),
            True,
            (False, False, "no_rule_matched"),
        ),
        ("an_unknown_comparison_runs", _running(0), None, True, (False, False, "no_rule_matched")),
        (
            "a_change_the_snapshots_cannot_show_runs",
            _running(0),
            _change(changed_lines=0, comparable=False),
            True,
            (False, False, "no_rule_matched"),
        ),
        (
            "a_gate_failure_keeps_running",
            PushGateDecision(skip=False, would_skip=False, reason="compare_unavailable"),
            _change(changed_lines=0),
            True,
            (False, False, "compare_unavailable"),
        ),
        (
            "an_earlier_skip_keeps_its_reason",
            PushGateDecision(skip=True, would_skip=True, reason="merge_only"),
            _change(changed_lines=0),
            True,
            (True, True, "merge_only"),
        ),
    ]
)
def test_zero_change_rule_skips_only_a_known_unchanged_pr_diff_in_the_treatment_arm(
    _name: str,
    decision: PushGateDecision,
    change: PRChange | None,
    enabled: bool,
    expected: tuple[bool, bool, str],
) -> None:
    result = apply_zero_change_rule(decision, change=change, enabled=enabled)
    assert (result.skip, result.would_skip, result.reason) == expected


def _snapshot(pr_files: list[PRFile], skipped_paths: list[str]) -> PRSnapshotArtefact:
    metadata = PRMetadata(
        number=1,
        title="t",
        state="open",
        draft=False,
        created_at="2026-10-01T00:00:00Z",
        updated_at="2026-10-01T00:00:00Z",
        author="a",
        base_branch="master",
        head_branch="feat",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )
    return PRSnapshotArtefact(head_sha="h", pr_metadata=metadata, pr_files=pr_files, skipped_paths=skipped_paths)


def _code(filename: str, code: str) -> PRFile:
    update = PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code=code)
    return PRFile(filename=filename, status="modified", additions=1, deletions=0, changes=[update])


@parameterized.expand(
    [
        ("same_reviewed_files", [_code("a.py", "x = 1")], [], [_code("a.py", "x = 1")], [], (0, False, True)),
        (
            "a_lockfile_in_the_pr_is_unseen_pnpm_lock_yaml",
            [_code("a.py", "x = 1")],
            ["pnpm-lock.yaml"],
            [_code("a.py", "x = 1")],
            ["pnpm-lock.yaml"],
            (0, False, False),
        ),
        (
            "a_lockfile_in_the_pr_is_unseen_bun_lockb",
            [_code("a.py", "x = 1")],
            ["bun.lockb"],
            [_code("a.py", "x = 1")],
            ["bun.lockb"],
            (0, False, False),
        ),
        (
            "a_lockfile_in_the_pr_is_unseen_npm_shrinkwrap_json",
            [_code("a.py", "x = 1")],
            ["npm-shrinkwrap.json"],
            [_code("a.py", "x = 1")],
            ["npm-shrinkwrap.json"],
            (0, False, False),
        ),
        (
            "a_file_without_a_patch_is_unseen_even_with_the_same_counts",
            [PRFile(filename="big.py", status="modified", additions=5000, deletions=0)],
            [],
            [PRFile(filename="big.py", status="modified", additions=5000, deletions=0)],
            [],
            (0, False, False),
        ),
        (
            "a_file_that_left_the_pr_has_no_delta_diff",
            [_code("a.py", "x = 1"), _code("b.py", "guard()")],
            [],
            [_code("a.py", "x = 1")],
            [],
            (1, False, False),
        ),
        (
            "a_manifest_change_is_a_dependency_change",
            [_code("package.json", '"a": "1"')],
            [],
            [_code("package.json", '"a": "2"')],
            [],
            (2, True, True),
        ),
    ]
)
def test_pr_change_is_comparable_only_when_the_snapshots_show_every_change(
    _name: str,
    earlier_files: list[PRFile],
    earlier_skipped: list[str],
    current_files: list[PRFile],
    current_skipped: list[str],
    expected: tuple[int, bool, bool],
) -> None:
    change = PRChange.between(_snapshot(earlier_files, earlier_skipped), _snapshot(current_files, current_skipped))
    assert (change.changed_lines, change.dependency_changed, change.comparable) == expected


@parameterized.expand(
    [
        ("small_later_push_in_the_treatment_arm", _running(5), {}, (True, True)),
        ("small_later_push_in_the_control_arm", _running(5), {"enabled": False}, (True, False)),
        ("first_follow_up_stays_whole", _running(5), {"run_index": 2}, (False, False)),
        ("over_the_share_stays_whole", _running(5), {"change": _change(changed_reviewable_lines=31)}, (False, False)),
        ("at_the_share_is_in", _running(5), {"change": _change(changed_reviewable_lines=30)}, (True, True)),
        (
            "no_reviewable_change_stays_whole",
            _running(5),
            {"change": _change(changed_reviewable_lines=0)},
            (False, False),
        ),
        ("a_dependency_change_stays_whole", _running(5), {"change": _change(dependency_changed=True)}, (False, False)),
        ("an_uncomparable_change_stays_whole", _running(5), {"change": _change(comparable=False)}, (False, False)),
        ("an_unknown_comparison_stays_whole", _running(5), {"change": None}, (False, False)),
        (
            "a_gate_failure_stays_whole",
            PushGateDecision(skip=False, would_skip=False, reason="compare_unavailable"),
            {},
            (False, False),
        ),
        (
            "a_skipped_push_reviews_nothing",
            PushGateDecision(skip=True, would_skip=True, reason="small_pr"),
            {},
            (False, False),
        ),
    ]
)
def test_delta_review_covers_only_small_comparable_later_pushes(
    _name: str, decision: PushGateDecision, overrides: dict[str, Any], expected: tuple[bool, bool]
) -> None:
    inputs: dict[str, Any] = {
        "run_index": 3,
        "change": _change(),
        "reviewable_lines": 1000,
        "enabled": True,
        **overrides,
    }
    result = plan_delta_review(decision, **inputs)
    assert (result.delta_eligible, result.delta_review) == expected


def test_a_gate_result_recorded_before_the_shadow_rules_went_away_still_decodes() -> None:
    old = {
        "skip": False,
        "would_skip": True,
        "reason": "next_push_likely",
        "probability": 0.9,
        "model": "posthog/hogference/jevk5-fp8-0.2",
        "next_push_probability": 0.842,
        "net_code_lines": 4,
        "small_change_deferrals": 1,
    }
    payload = DataConverter.default.payload_converter.to_payloads([old])[0]

    decision = DataConverter.default.payload_converter.from_payloads([payload], [PushGateDecision])[0]

    assert (decision.skip, decision.would_skip, decision.reason) == (False, True, "next_push_likely")
