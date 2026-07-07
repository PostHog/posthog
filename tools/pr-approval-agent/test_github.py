"""Tests for GitHub review normalization used by the PR approval agent."""

import re

import pytest

import github
from github import (
    _normalize_discussion_for_prompt,
    _normalize_reviews_for_prompt,
    _reaction_emoji,
    _trusted_reactor_predicate,
    is_bot_author,
)


def test_normalize_reviews_marks_current_head_and_preserves_stale_reviews() -> None:
    head_sha = "072cdd75592bfd0bf0c016209385f20f85a45201"
    current_review = {
        "user": {"login": "copilot-pull-request-reviewer", "type": "Bot"},
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
            "user": "copilot-pull-request-reviewer",
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


@pytest.mark.parametrize(
    "login,expected_count",
    [
        pytest.param("stamphog[bot]", 0, id="own-refuse-comment-review"),
        pytest.param("github-actions[bot]", 0, id="own-approve-review"),
        pytest.param("greptile-apps[bot]", 1, id="other-bot-kept"),
    ],
)
def test_normalize_reviews_excludes_stamphogs_own_prior_reviews(login: str, expected_count: int) -> None:
    # Feeding stamphog's own stale reviews back into the prompt makes the next
    # run read them as third-party claims about state that no longer matches —
    # it then suspects tampering and refuses forever.
    normalized = _normalize_reviews_for_prompt(
        [
            {
                "user": {"login": login, "type": "Bot"},
                "state": "COMMENTED",
                "body": "Refusing: reviews in flight",
                "commit_id": "abc123",
                "submitted_at": "2026-04-07T20:14:03Z",
                "author_association": "NONE",
            }
        ],
        "abc123",
    )

    assert len(normalized) == expected_count


@pytest.mark.parametrize(
    "login,expected_count",
    [
        pytest.param("stamphog[bot]", 0, id="own-refuse-comment-excluded"),
        pytest.param("github-actions[bot]", 0, id="own-approve-identity-excluded"),
        pytest.param("greptile-apps[bot]", 1, id="other-bot-kept"),
        pytest.param("alice", 1, id="human-kept"),
    ],
)
def test_normalize_discussion_excludes_stamphogs_own_comments(login: str, expected_count: int) -> None:
    # Same exclusion as reviews/inline: stamphog's own discussion comments
    # describe an earlier snapshot; feeding them back makes the next run read
    # its own verdict as a third-party claim about stale state.
    normalized = _normalize_discussion_for_prompt(
        [{"user": {"login": login}, "body": "a comment", "created_at": "2026-04-07T20:14:03Z"}]
    )

    assert len(normalized) == expected_count


@pytest.mark.parametrize(
    "content,expected",
    [
        pytest.param("+1", "👍", id="rest-thumbs-up"),
        pytest.param("THUMBS_UP", "👍", id="graphql-thumbs-up"),
        pytest.param("-1", "👎", id="rest-thumbs-down"),
        pytest.param("EYES", "👀", id="graphql-eyes"),
        pytest.param("sparkle", "sparkle", id="unknown-passthrough"),
    ],
)
def test_reaction_emoji_normalizes_rest_and_graphql(content: str, expected: str) -> None:
    assert _reaction_emoji(content) == expected


@pytest.mark.parametrize(
    "login,expected",
    [
        pytest.param("prauthor", False, id="author-self-reaction"),
        pytest.param("ghost", False, id="deleted-user"),
        pytest.param("", False, id="empty-login"),
        pytest.param("greptile-apps[bot]", True, id="allowlisted-bot"),
        pytest.param("inkeep[bot]", False, id="unlisted-bot"),
        pytest.param("teammate", True, id="org-member"),
        pytest.param("outsider", False, id="external-non-member"),
    ],
)
def test_trusted_reactor_predicate_gates_untrusted_and_author(
    monkeypatch: pytest.MonkeyPatch, login: str, expected: bool
) -> None:
    monkeypatch.setattr(github, "_is_org_member", lambda org, member: member == "teammate")
    is_trusted = _trusted_reactor_predicate("PostHog/posthog", author="prauthor")
    assert is_trusted(login) is expected


@pytest.mark.parametrize(
    "user,expected",
    [
        pytest.param({"login": "mendral-app[bot]", "type": "Bot"}, True, id="github-app-type"),
        pytest.param({"login": "dependabot[bot]", "type": "Bot"}, True, id="dependabot"),
        pytest.param({"login": "some-tool[bot]", "type": "User"}, True, id="bot-suffix-misreported-type"),
        pytest.param({"login": "posthog-bot", "type": "User"}, True, id="machine-user"),
        pytest.param({"login": "POSTHOG-BOT", "type": "User"}, True, id="machine-user-case-insensitive"),
        pytest.param({"login": "alice", "type": "User"}, False, id="human"),
        pytest.param({}, False, id="missing-user"),
    ],
)
def test_is_bot_author(user: dict, expected: bool) -> None:
    assert is_bot_author(user) is expected


def _worst_case_node_count(query: str) -> int:
    # Mirrors GitHub's pre-execution node-limit check: each connection requests
    # `first` nodes multiplied by the `first` of every ancestor connection.
    total = 0
    multipliers = [1]
    pending = 1
    for match in re.finditer(r"first:\s*(\d+)|[{}]", query):
        if match.group(1):
            pending = int(match.group(1))
            total += multipliers[-1] * pending
        elif match.group(0) == "{":
            multipliers.append(multipliers[-1] * pending)
            pending = 1
        else:
            multipliers.pop()
    return total


def test_review_threads_query_stays_under_github_node_limit() -> None:
    # GitHub rejects any GraphQL query whose worst-case node count exceeds
    # 500,000 before executing it, which hard-fails the review on every PR.
    assert _worst_case_node_count(github._REVIEW_THREADS_QUERY) < 500_000


@pytest.mark.parametrize(
    "login,expected_users",
    [
        pytest.param("stamphog[bot]", ["greptile-apps[bot]"], id="own-inline-comment-excluded"),
        pytest.param("github-actions[bot]", ["greptile-apps[bot]"], id="own-approve-identity-excluded"),
        pytest.param(
            "copilot-pull-request-reviewer[bot]",
            ["copilot-pull-request-reviewer[bot]", "greptile-apps[bot]"],
            id="other-bot-kept",
        ),
    ],
)
def test_fetch_threads_excludes_stamphogs_own_inline_comments(
    monkeypatch: pytest.MonkeyPatch, login: str, expected_users: list[str]
) -> None:
    # Stamphog's earlier verdicts fed back through inline comments read as
    # third-party claims about a stale snapshot — later runs then suspect
    # impersonation and refuse forever, exactly like stale top-level reviews.
    def fake_graphql(query: str, variables: dict | None = None) -> dict:
        def comment(user: str) -> dict:
            return {
                "author": {"login": user, "__typename": "Bot"},
                "authorAssociation": "NONE",
                "body": f"comment from {user}",
                "databaseId": 1,
                "replyTo": None,
                "reactions": {"nodes": []},
            }

        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reactions": {"nodes": []},
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "isOutdated": False,
                                    "path": "posthog/api/insight.py",
                                    "line": 42,
                                    "comments": {
                                        "pageInfo": {"hasNextPage": False},
                                        "nodes": [comment(login), comment("greptile-apps[bot]")],
                                    },
                                }
                            ],
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(github, "_gh_graphql", fake_graphql)
    monkeypatch.setattr(github, "_is_org_member", lambda org, member: False)

    comments, _ = github._fetch_threads_and_reactions("PostHog/posthog", 1, author="alice")

    assert [c["user"] for c in comments] == expected_users
