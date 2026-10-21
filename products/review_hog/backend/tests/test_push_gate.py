from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from redis.exceptions import RedisError

from posthog.llm.system_one import NoulAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult
from posthog.redis import TEST_clear_clients, get_client
from posthog.token_bucket import BucketUnavailable, TEST_reset_scripts

from products.review_hog.backend.reviewer.push_gate import (
    PUSH_GATE_MODEL,
    PushGate,
    PushGateDecision,
    _NextPushCell,
    apply_draft_rule,
    apply_follow_up_value_rules,
    apply_next_push_rule,
    apply_throttle,
    next_push_probability,
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


def _net_file(filename: str, lines: int) -> dict[str, Any]:
    return {"filename": filename, "additions": lines, "deletions": 0}


def _net_compare(files: list[dict[str, Any]], *, status: str = "ahead") -> dict[str, Any]:
    return {"status": status, "merge_base_commit": {"sha": "old"}, "files": files}


# Large enough that the small-change rule leaves the push to the rules after it.
_LARGE_NET_FILES = [_net_file("posthog/billing.py", 40)]


def _pr(commits: list[dict[str, Any]], files: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_commits": len(commits), "commits": commits, "files": files}


def _push(
    *,
    new_commits: list[dict[str, Any]],
    pr_files: list[dict[str, Any]],
    own_commit_files: list[dict[str, Any]] | None = None,
    net_files: list[dict[str, Any]] | None = None,
    head: str = "new",
) -> dict[str, dict[str, Any] | None]:
    return {
        "compare/master...old": _pr([_commit("a")], [_file("posthog/billing.py", _BILLING)]),
        f"compare/master...{head}": _pr(new_commits, pr_files),
        f"compare/old...{head}": _net_compare(_LARGE_NET_FILES if net_files is None else net_files),
        "commits/c": {"files": own_commit_files or []},
    }


def _github(responses: dict[str, dict[str, Any] | None]):
    def request(method: str, path: str, **kwargs: Any) -> MagicMock:
        response = responses[path.removeprefix("/repos/PostHog/posthog/")]
        if response is None:
            raise GitHubAPIError("gone", status=404)
        return MagicMock(json=MagicMock(return_value=response))

    return request


def _decide(
    responses: dict[str, dict[str, Any] | None],
    system_one: MagicMock | None = None,
    *,
    draft: bool = False,
    follow_up: int | None = None,
    pr_lines: int | None = None,
    head: str = "new",
    record: bool = False,
    gate: PushGate | None = None,
) -> PushGateDecision:
    gate = gate or PushGate(team_id=1, repository="PostHog/posthog", token="t", installation_id="9")
    with (
        patch(f"{_MODULE}.github_api_request", side_effect=_github(responses)),
        patch(f"{_MODULE}.build_system_one_client", MagicMock(return_value=system_one or MagicMock())),
        patch(f"{_MODULE}.posthog_app_login", return_value="reviewhog[bot]"),
    ):
        decision = gate.decide(previous_head_sha="old", head_sha=head, base_branch="master", pr_number=1)
    if draft:
        decision = apply_draft_rule(decision, draft=True)
    else:
        decision = apply_next_push_rule(decision, follow_up=follow_up, pr_lines=pr_lines)
    if record:
        decision = gate.record_small_change_streak(decision, pr_number=1, head_sha=head)
    return decision


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
    # The README's lines stay out of the push size, like they stay out of the state.
    assert decision.own_code_lines == 2
    call = system_one.decide.call_args.kwargs
    # The threshold was calibrated on exactly this state: own code patches, docs dropped.
    assert call["state"] == f"--- posthog/billing.py\n{_BILLING_FIX}"
    assert "round" not in str(call["questions"]["alters"].instructions)


def test_push_gate_logs_no_push_size_when_a_commit_lists_a_full_page_of_files() -> None:
    full_page = [_file(f"posthog/module_{n}.py") for n in range(300)]
    push = _push(
        new_commits=[_commit("a"), _commit("c")],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
        own_commit_files=full_page,
    )
    decision = _decide(push, _system_one(0.8))
    assert (decision.reason, decision.own_code_lines) == ("system_one_above_threshold", None)


def test_push_gate_reviews_a_push_that_mixes_reviewhog_and_author_commits() -> None:
    push = _push(
        new_commits=[_commit("a"), _own_commit("r"), _commit("c")],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
        own_commit_files=[_file("posthog/billing.py", _BILLING_FIX)],
    )
    decision = _decide({**push, "commits/r": {"files": []}}, _system_one(0.99))
    assert (decision.skip, decision.reason) == (False, "system_one_above_threshold")


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
    decision = _decide({**push, "commits/s": {"files": [_file("posthog/billing.py", _BILLING_FIX)]}}, _system_one(0.99))
    assert decision.reason != "reviewhog_commits_only"


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


@parameterized.expand(
    [
        ("code_push", _CODE_PUSH, (True, True, "draft", 0.8, PUSH_GATE_MODEL, 2)),
        # A shadow match does not skip, so the draft rule decides the push.
        (
            "docs_only_shadow",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING), _file("README.md")],
                own_commit_files=[_file("README.md")],
            ),
            (True, True, "draft", None, None, 0),
        ),
        # A rule that skips on its own is more specific than the draft state.
        (
            "force_push_back",
            _push(new_commits=[_commit("a")], pr_files=[_file("posthog/billing.py", _BILLING)]),
            (True, True, "no_new_commits", None, None, None),
        ),
    ]
)
def test_push_gate_skips_a_draft_push_and_keeps_the_system_one_answer(
    _name: str,
    responses: dict[str, dict[str, Any] | None],
    expected: tuple[bool, bool, str, float | None, str | None, int | None],
) -> None:
    decision = _decide(responses, _system_one(0.8), draft=True, follow_up=7, pr_lines=150)
    assert decision.next_push_probability is None
    assert (
        decision.skip,
        decision.would_skip,
        decision.reason,
        decision.probability,
        decision.model,
        decision.own_code_lines,
    ) == expected


# Autouse because every gate decision on a code push reads the small-change counter.
@pytest.fixture(autouse=True)
def empty_redis() -> Iterator[None]:
    TEST_clear_clients()
    TEST_reset_scripts()
    # The fake Redis server outlives its clients, so a counter from an earlier test would stay.
    get_client().flushdb()
    yield
    TEST_clear_clients()
    TEST_reset_scripts()


def test_push_gate_throttles_the_third_push_in_half_an_hour(empty_redis: None) -> None:
    reviewed = PushGateDecision(skip=False, would_skip=False, reason="system_one_above_threshold", probability=0.9)
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
            outcomes.append((result.skip, result.reason, result.probability))

    assert outcomes == [
        (True, "draft", None),
        (False, "system_one_above_threshold", 0.9),
        (False, "system_one_above_threshold", 0.9),
        (False, "system_one_above_threshold", 0.9),
        (False, "system_one_above_threshold", 0.9),
        (True, "throttled", 0.9),
        (True, "throttled", 0.9),
        (False, "system_one_above_threshold", 0.9),
        (True, "throttled", 0.9),
    ]


def test_push_gate_reviews_the_push_when_redis_is_down(empty_redis: None) -> None:
    reviewed = PushGateDecision(skip=False, would_skip=False, reason="system_one_above_threshold")
    with patch(f"{_MODULE}.consume", return_value=BucketUnavailable(error="down")):
        assert apply_throttle(reviewed, report_id="pr-a", head_sha="a1") == reviewed


@parameterized.expand(
    [
        ("size_cell", 1, 150, {}, 0.559),
        ("size_band_upper_edge", 1, 200, {}, 0.559),
        ("capped_at_the_eighth_follow_up", 12, 5000, {}, 0.842),
        ("small_cell_falls_back", 7, 150, {(7, "<=200"): _NextPushCell(probability=0.900, prs=9)}, 0.842),
        ("no_follow_up_yet", 0, 150, {}, None),
    ]
)
def test_next_push_probability_reads_the_size_cell_or_falls_back(
    _name: str, follow_up: int, pr_lines: int, cells: dict[Any, _NextPushCell], expected: float | None
) -> None:
    with patch.dict(f"{_MODULE}._NEXT_PUSH_BY_FOLLOW_UP_AND_SIZE", cells):
        assert next_push_probability(follow_up=follow_up, pr_lines=pr_lines) == expected


_DOCS_PUSH = _push(
    new_commits=[_commit("a"), _commit("c")],
    pr_files=[_file("posthog/billing.py", _BILLING), _file("README.md")],
    own_commit_files=[_file("README.md")],
)


@parameterized.expand(
    [
        ("below_threshold_runs", _CODE_PUSH, 0.8, 1, 150, (False, False, "system_one_above_threshold", 0.559)),
        ("at_threshold_shadow_skip", _CODE_PUSH, 0.8, 8, 5000, (False, True, "next_push_likely", 0.842)),
        ("unknown_size_runs", _CODE_PUSH, 0.8, 7, None, (False, False, "system_one_above_threshold", None)),
        ("docs_only_shadow_keeps_reason", _DOCS_PUSH, 0.8, 7, 150, (False, True, "docs_only", 0.900)),
        ("system_one_shadow_keeps_reason", _CODE_PUSH, 0.1, 7, 150, (False, True, "system_one_below_threshold", 0.900)),
        (
            "skipping_rule_keeps_reason",
            _push(new_commits=[_commit("a")], pr_files=[_file("posthog/billing.py", _BILLING)]),
            0.8,
            7,
            150,
            (True, True, "no_new_commits", 0.900),
        ),
    ]
)
def test_push_gate_records_a_likely_next_push_without_skipping(
    _name: str,
    responses: dict[str, dict[str, Any] | None],
    system_one_probability: float,
    follow_up: int,
    pr_lines: int | None,
    expected: tuple[bool, bool, str, float | None],
) -> None:
    with patch(f"{_MODULE}.NEXT_PUSH_SKIP_AT", 0.842):
        decision = _decide(responses, _system_one(system_one_probability), follow_up=follow_up, pr_lines=pr_lines)
    assert (decision.skip, decision.would_skip, decision.reason, decision.next_push_probability) == expected


def _small_push(head: str, net_files: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    return _push(
        new_commits=[_commit("a"), _commit("c")],
        pr_files=[_file("posthog/billing.py", _BILLING_FIX)],
        own_commit_files=[_file("posthog/billing.py", _BILLING_FIX)],
        net_files=net_files,
        head=head,
    )


@parameterized.expand(
    [
        (
            "small_push_shadow",
            _small_push("new", [_net_file("posthog/billing.py", 4), _net_file("README.md", 50)]),
            (False, True, "small_change", 4, 1),
        ),
        (
            "eleven_lines_runs",
            _small_push("new", [_net_file("posthog/billing.py", 11)]),
            (False, False, "system_one_above_threshold", 11, 0),
        ),
        (
            "capped_compare_is_unknown",
            _small_push("new", [_net_file(f"posthog/module_{n}.py", 1) for n in range(300)]),
            (False, False, "system_one_above_threshold", None, 0),
        ),
        (
            "rebased_head_is_unknown",
            {
                **_small_push("new", []),
                "compare/old...new": _net_compare([_net_file("posthog/billing.py", 3)], status="diverged"),
            },
            (False, False, "system_one_above_threshold", None, 0),
        ),
        (
            "missing_count_is_unknown",
            _small_push("new", [{"filename": "posthog/billing.py"}]),
            (False, False, "system_one_above_threshold", None, 0),
        ),
        (
            "no_code_lines_stays_docs_only",
            {**_DOCS_PUSH, "compare/old...new": _net_compare([_net_file("posthog/billing.py", 3)])},
            (False, True, "docs_only", None, 0),
        ),
    ]
)
def test_push_gate_defers_a_push_with_few_net_code_lines(
    _name: str,
    responses: dict[str, dict[str, Any] | None],
    expected: tuple[bool, bool, str, int | None, int | None],
) -> None:
    decision = _decide(responses, _system_one(0.8))
    assert (
        decision.skip,
        decision.would_skip,
        decision.reason,
        decision.net_code_lines,
        decision.small_change_deferrals,
    ) == expected


def test_push_gate_reviews_the_small_push_after_two_deferrals() -> None:
    small = [_net_file("posthog/billing.py", 3)]
    pushes = [
        ("n1", small),
        ("n2", small),
        ("n2", small),
        ("n3", small),
        ("n4", small),
        ("n5", [_net_file("posthog/billing.py", 30)]),
        ("n6", small),
    ]
    outcomes = []
    for head, net_files in pushes:
        decision = _decide(_small_push(head, net_files), _system_one(0.8), head=head, record=True)
        outcomes.append((decision.reason, decision.small_change_deferrals))

    assert outcomes == [
        ("small_change", 1),
        ("small_change", 2),
        ("small_change", 2),
        ("system_one_above_threshold", 0),
        ("small_change", 1),
        ("system_one_above_threshold", 0),
        ("small_change", 1),
    ]


def test_push_gate_reviews_a_small_push_whose_count_another_turn_moved() -> None:
    small = [_net_file("posthog/billing.py", 3)]
    _decide(_small_push("n1", small), _system_one(0.8), head="n1", record=True)
    first = PushGate(team_id=1, repository="PostHog/posthog", token="t", installation_id="9")
    second = PushGate(team_id=1, repository="PostHog/posthog", token="t", installation_id="9")
    overlapping = [
        (first, "n2", _decide(_small_push("n2", small), _system_one(0.8), head="n2", gate=first)),
        (second, "n3", _decide(_small_push("n3", small), _system_one(0.8), head="n3", gate=second)),
    ]

    recorded = [
        gate.record_small_change_streak(decision, pr_number=1, head_sha=head) for gate, head, decision in overlapping
    ]

    assert [(decision.reason, decision.would_skip) for decision in recorded] == [
        ("small_change", True),
        ("small_change_not_stored", False),
    ]
    assert get_client().get("reviewhog_small_change_deferrals:PostHog/posthog:1") == b"n2:2"


@parameterized.expand(
    [
        ("read_fails", True, ("system_one_above_threshold", 3, None)),
        ("write_fails", False, ("small_change_not_stored", 3, 1)),
    ]
)
def test_push_gate_reviews_a_small_push_when_redis_fails(
    _name: str, read_fails: bool, expected: tuple[str, int, int | None]
) -> None:
    redis = MagicMock()
    if read_fails:
        redis.get.side_effect = RedisError("down")
    else:
        redis.get.return_value = None
        redis.register_script.return_value.side_effect = RedisError("read only")
    with patch(f"{_MODULE}.get_client", return_value=redis):
        decision = _decide(_small_push("new", [_net_file("posthog/billing.py", 3)]), _system_one(0.8), record=True)
    assert (decision.reason, decision.net_code_lines, decision.small_change_deferrals) == expected


@parameterized.expand(
    [
        (
            "reviewed_docs_push_resets",
            _push(
                new_commits=[_commit("a"), _commit("c")],
                pr_files=[_file("posthog/billing.py", _BILLING), _file("README.md")],
                own_commit_files=[_file("README.md")],
                head="n3",
            ),
            False,
            [("docs_only", 0), ("small_change", 1)],
        ),
        (
            "skipped_merge_keeps_streak",
            _push(
                new_commits=[_commit("a"), _commit("m", merge=True)],
                pr_files=[_file("posthog/billing.py", _BILLING_AFTER_MERGE)],
                head="n3",
            ),
            False,
            [("merge_only", None), ("system_one_above_threshold", 0)],
        ),
        (
            "draft_skip_of_the_forced_review_keeps_streak",
            _small_push("n3", [_net_file("posthog/billing.py", 3)]),
            True,
            [("draft", 0), ("system_one_above_threshold", 0)],
        ),
    ]
)
def test_push_gate_small_change_streak_after_a_push_another_rule_decides(
    _name: str,
    middle_push: dict[str, dict[str, Any] | None],
    middle_draft: bool,
    expected_tail: list[tuple[str, int | None]],
) -> None:
    small = [_net_file("posthog/billing.py", 3)]
    pushes = [
        ("n1", _small_push("n1", small), False),
        ("n2", _small_push("n2", small), False),
        ("n3", middle_push, middle_draft),
        ("n4", _small_push("n4", small), False),
    ]
    outcomes = []
    for head, responses, draft in pushes:
        decision = _decide(responses, _system_one(0.8), draft=draft, head=head, record=True)
        outcomes.append((decision.reason, decision.small_change_deferrals))

    assert outcomes == [("small_change", 1), ("small_change", 2), *expected_tail]


def _running(own_code_lines: int | None) -> PushGateDecision:
    return PushGateDecision(
        skip=False,
        would_skip=False,
        reason="system_one_above_threshold",
        probability=0.8,
        own_code_lines=own_code_lines,
    )


@parameterized.expand(
    [
        ("ninth_review", _running(200), 9, 2000, 3, (True, True, "late_follow_up")),
        ("eighth_review_runs", _running(200), 8, 2000, 3, (False, False, "system_one_above_threshold")),
        ("pr_under_150_lines", _running(200), 3, 149, 3, (True, True, "small_pr")),
        ("pr_of_150_lines_runs", _running(200), 3, 150, 3, (False, False, "system_one_above_threshold")),
        ("quiet_review_and_small_push", _running(30), 3, 400, 0, (True, True, "quiet_small_push")),
        ("quiet_review_and_larger_push_runs", _running(31), 3, 400, 0, (False, False, "system_one_above_threshold")),
        ("review_with_a_finding_runs", _running(5), 3, 400, 1, (False, False, "system_one_above_threshold")),
        ("unknown_inputs_run", _running(None), 3, None, None, (False, False, "system_one_above_threshold")),
        (
            "shadow_match_skips",
            PushGateDecision(skip=False, would_skip=True, reason="docs_only", own_code_lines=0),
            3,
            400,
            0,
            (True, True, "quiet_small_push"),
        ),
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


def test_next_push_rule_keeps_the_value_rule_inputs() -> None:
    decision = replace(_running(200), reviewable_lines=400, previous_findings=2)
    with patch(f"{_MODULE}.NEXT_PUSH_SKIP_AT", 0.0):
        result = apply_next_push_rule(decision, follow_up=4, pr_lines=400)
    assert (result.reason, result.reviewable_lines, result.previous_findings) == ("next_push_likely", 400, 2)
