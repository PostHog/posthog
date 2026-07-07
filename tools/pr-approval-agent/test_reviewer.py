"""Tests for prompt sanitization in reviewer.py."""

import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock

# reviewer.py is imported by a uv-script; its `claude_agent_sdk` dep is
# installed by `uv run`, not the test venv. Stub the modules it imports.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

from github import PRData  # noqa: E402
from reviewer import Reviewer, _sanitize_untrusted, _truncate_inline_comments  # noqa: E402


def _pr(**overrides: object) -> PRData:
    defaults: dict = {
        "number": 1,
        "repo": "PostHog/posthog",
        "title": "t",
        "state": "OPEN",
        "draft": False,
        "mergeable_state": "clean",
        "author": "alice",
        "labels": [],
        "base_sha": "a",
        "head_sha": "h",
        "files": [],
        "reviews": [],
        "review_comments": [],
        "check_runs": [],
    }
    defaults.update(overrides)
    return PRData(**defaults)


def _prompt(pr: PRData, assurance: dict | None = None) -> str:
    cl = {
        "tier": "T1-agent",
        "t1_subclass": "T1b-small",
        "breadth": "narrow",
        "commit_type": "fix",
        "familiarity": None,
        "ownership": {},
        "assurance": assurance,
    }
    gate_context = {"gate_verdict": "PENDING", "gates": []}
    reviewer = Reviewer(Path("."))
    return reviewer._build_review_prompt(pr, cl, gate_context, Path("/tmp/diff.patch"))


@pytest.mark.parametrize(
    "text,expected",
    [
        # Reviewer bots express verdicts as emoji in review bodies; stripping
        # them garbles quoted comments into text a later run can misread as
        # an injection attempt.
        pytest.param(
            "both have 👀 reactions — that overrides the 👍s present.",
            "both have 👀 reactions — that overrides the 👍s present.",
            id="emoji-and-dash-survive",
        ),
        pytest.param("ein Häkchen ✓ 中文", "ein Häkchen ✓ 中文", id="non-ascii-text-survives"),
        pytest.param("zero\u200bwidth\u200e", "zerowidth", id="zero-width-stripped"),
        # ZWJ interleaving (i\u200dg\u200dn\u200do\u200dr\u200de) is a smuggling vector, so it
        # is stripped too; composite emoji degrade to visible components.
        pytest.param("i\u200dg\u200dnore 🧑\u200d💻", "ignore 🧑💻", id="zwj-stripped-emoji-degrades-visibly"),
        pytest.param("a\u202egnihton\u202c od\u2066b\u2069\u061c", "agnihton odb", id="bidi-controls-stripped"),
        pytest.param("hidden\U000e0041\U000e0042tag", "hiddentag", id="tags-block-smuggling-stripped"),
        pytest.param("bell\x07cr\rok\ntab\t.", "bellcrok\ntab\t.", id="control-chars-stripped-keeps-nl-tab"),
    ],
)
def test_sanitize_untrusted_strips_invisible_keeps_visible(text: str, expected: str) -> None:
    assert _sanitize_untrusted(text) == expected


@pytest.mark.parametrize(
    "body,rendered",
    [
        pytest.param("Adds a flag​to X", "Adds a flagto X", id="sanitized-body"),
        pytest.param("", "(none)", id="empty-body-shows-none"),
    ],
)
def test_prompt_renders_description_in_untrusted_region(body: str, rendered: str) -> None:
    prompt = _prompt(_pr(body=body))
    begin = prompt.index("BEGIN UNTRUSTED CONTENT")
    header = prompt.index("PR description:")
    assert header > begin
    assert rendered in prompt[header:]


@pytest.mark.parametrize(
    "count,omission_line,absent_body",
    [
        pytest.param(50, "", None, id="at-cap-no-omission"),
        # Keep-ends, not newest-only: the oldest comments carry maintainer holds,
        # so over the cap we drop the middle and keep both the first 15 and last 35.
        pytest.param(65, "(15 middle comments omitted)", "comment020", id="over-cap-drops-middle"),
    ],
)
def test_prompt_discussion_keeps_both_ends(count: int, omission_line: str, absent_body: str | None) -> None:
    discussion = [{"user": f"u{i}", "body": f"comment{i:03d}", "created_at": None} for i in range(count)]
    prompt = _prompt(_pr(discussion=discussion))

    assert "comment000" in prompt  # oldest is always kept
    assert f"comment{count - 1:03d}" in prompt  # newest is always kept
    if omission_line:
        assert omission_line in prompt
    else:
        assert "middle comments omitted" not in prompt
    if absent_body:
        assert absent_body not in prompt


def test_prompt_truncates_long_review_body() -> None:
    # Guards the widened cap: a revert to the old 500-char limit would drop the
    # 2500th character and fail this.
    review = {"user": "bob", "state": "COMMENTED", "body": "X" * 3000, "is_current_head": True, "commit_id": "h"}
    prompt = _prompt(_pr(reviews=[review]))

    assert "X" * 2500 in prompt
    assert "X" * 2501 not in prompt


@pytest.mark.parametrize(
    "assurance,expected",
    [
        pytest.param(
            {"head_approvals": ["bob"], "head_commented": 0, "unresolved_threads": 3, "discussion": 4},
            "Assurance: 1 current-head approval (@bob); 3 unresolved inline threads; 4 discussion comments",
            id="approvals-and-unresolved",
        ),
        pytest.param(
            {"head_approvals": [], "head_commented": 0, "unresolved_threads": 1, "discussion": 0},
            "Assurance: 1 unresolved inline thread",
            id="singular-thread-no-plural-s",
        ),
        pytest.param(
            {"head_approvals": [], "head_commented": 0, "unresolved_threads": 0, "discussion": 0},
            "Assurance: no reviews or comments yet",
            id="nothing-yet",
        ),
    ],
)
def test_format_assurance_line(assurance: dict, expected: str) -> None:
    assert Reviewer(Path("."))._format_assurance({"assurance": assurance}) == expected


@pytest.mark.parametrize(
    "count,kept_ids,dropped_id,omission",
    [
        # An unresolved comment older than the dropped resolved ones must survive:
        # the norms key on unresolved threads, so truncation can't sacrifice one.
        pytest.param(3, {"keep-unresolved", "b", "c"}, "old-resolved", "(1 older resolved/outdated comments omitted)"),
    ],
)
def test_inline_truncation_keeps_unresolved_drops_resolved(
    count: int, kept_ids: set[str], dropped_id: str, omission: str
) -> None:
    def comment(body: str, *, resolved: bool) -> dict:
        return {"user": "r", "body": body, "path": "f.py", "is_resolved": resolved, "in_reply_to_id": None}

    # Oldest-first: a resolved comment, then an unresolved one, then fillers.
    comments = [
        comment("old-resolved", resolved=True),
        comment("keep-unresolved", resolved=False),
        comment("b", resolved=False),
        comment("c", resolved=False),
    ]
    shown, line = _truncate_inline_comments(comments, cap=count)

    assert {c["body"] for c in shown} == kept_ids
    assert all(c["body"] != dropped_id for c in shown)
    assert line == omission
