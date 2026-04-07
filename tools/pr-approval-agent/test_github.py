"""Tests for GitHub review normalization used by the PR approval agent."""

import pytest

from github import _normalize_reviews_for_prompt


def test_normalize_reviews_marks_current_head_and_preserves_stale_reviews() -> None:
    head_sha = "072cdd75592bfd0bf0c016209385f20f85a45201"
    current_review = {
        "user": {"login": "stamphog", "type": "Bot"},
        "state": "COMMENTED",
        "body": "Current head concern",
        "commit_id": head_sha,
        "submitted_at": "2026-04-07T20:14:03Z",
        "author_association": "BOT",
    }
    stale_review = {
        "user": {"login": "greptile-apps", "type": "Bot"},
        "state": "COMMENTED",
        "body": "Older concern",
        "commit_id": "3c51bb8de4c73929c5266986118a14b966cb6831",
        "submitted_at": "2026-04-07T20:02:32Z",
        "author_association": "BOT",
    }

    normalized = _normalize_reviews_for_prompt([current_review, stale_review], head_sha)

    assert normalized == [
        {
            "user": "stamphog",
            "state": "COMMENTED",
            "body": "Current head concern",
            "commit_id": head_sha,
            "is_current_head": True,
            "submitted_at": "2026-04-07T20:14:03Z",
        },
        {
            "user": "greptile-apps",
            "state": "COMMENTED",
            "body": "Older concern",
            "commit_id": "3c51bb8de4c73929c5266986118a14b966cb6831",
            "is_current_head": False,
            "submitted_at": "2026-04-07T20:02:32Z",
        },
    ]


@pytest.mark.parametrize(
    "author_association,user_type,expected_count",
    [
        pytest.param("MEMBER", "User", 1, id="member-reviewer"),
        pytest.param("OWNER", "User", 1, id="owner-reviewer"),
        pytest.param("COLLABORATOR", "User", 1, id="collaborator-reviewer"),
        pytest.param("BOT", "User", 1, id="bot-association"),
        pytest.param("NONE", "Bot", 1, id="bot-user-type"),
        pytest.param("NONE", "User", 0, id="untrusted-reviewer"),
    ],
)
def test_normalize_reviews_filters_by_trust_source(
    author_association: str, user_type: str, expected_count: int
) -> None:
    normalized = _normalize_reviews_for_prompt(
        [
            {
                "user": {"login": "reviewer", "type": user_type},
                "state": "COMMENTED",
                "body": "Review body",
                "commit_id": "abc123",
                "submitted_at": "2026-04-07T20:14:03Z",
                "author_association": author_association,
            }
        ],
        "abc123",
    )

    assert len(normalized) == expected_count
