import sys
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import github  # noqa: E402
import review_pr  # noqa: E402
import familiarity  # noqa: E402
import review_local  # noqa: E402
import openai_reviewer  # noqa: E402
from test_review_local import _thread_comment  # noqa: E402

_FINDING = "src/app.py: handler() returns None when the cache is empty."
_BOT_ROOT = _thread_comment("posthog", _FINDING, is_bot=True)
_AUTHOR_REPLY = _thread_comment("alice", "Not a bug: the cache is filled at import.")


def _rejected(*, holds: bool = True, category: str = "other") -> dict:
    return {
        "thread": "T1",
        "concern": _FINDING,
        "category": category,
        "rejection_holds": holds,
        "evidence": "src/app.py fills the cache before handler() can run.",
    }


def _commit(repo: Path, body: str) -> str:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text(body)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "chore: change the handler"], check=True, capture_output=True)
    return subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


class _JudgingReviewer(openai_reviewer.OpenAIReviewer):
    facts: dict = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        usage = SimpleNamespace(
            input_tokens=1,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=1,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        )
        answer = SimpleNamespace(
            status="completed",
            output=[SimpleNamespace(type="message")],
            output_text=json.dumps(self.facts),
            usage=usage,
        )
        self.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: answer))


@pytest.mark.parametrize(
    "comments, rejected, expected",
    [
        pytest.param([_BOT_ROOT, _AUTHOR_REPLY], _rejected(), "APPROVED", id="holds"),
        pytest.param([_BOT_ROOT, _AUTHOR_REPLY], _rejected(holds=False), "REFUSED", id="rejection-does-not-hold"),
        pytest.param([_BOT_ROOT, _AUTHOR_REPLY], _rejected(category="auth"), "REFUSED", id="strict-category"),
        pytest.param(
            [_thread_comment("carol", _FINDING), _AUTHOR_REPLY], _rejected(), "REFUSED", id="raised-by-a-person"
        ),
        pytest.param(
            [_BOT_ROOT, _AUTHOR_REPLY, _thread_comment("carol", "I still think it can be empty.")],
            _rejected(),
            "REFUSED",
            id="a-person-joined-the-thread",
        ),
        pytest.param(
            [_BOT_ROOT, _AUTHOR_REPLY], {**_rejected(), "thread": "[T1]"}, "APPROVED", id="thread-id-as-tagged"
        ),
        pytest.param(
            [_BOT_ROOT, _AUTHOR_REPLY, _thread_comment("posthog", "I still think it can be empty.")],
            _rejected(),
            "REFUSED",
            id="a-person-with-the-bots-login-joined",
        ),
        pytest.param(
            [_BOT_ROOT, _AUTHOR_REPLY, _thread_comment("mallory", "It can be empty.", association="NONE")],
            _rejected(),
            "REFUSED",
            id="an-untrusted-person-joined-the-thread",
        ),
        pytest.param([_BOT_ROOT], _rejected(), "REFUSED", id="author-never-replied"),
        pytest.param(
            [_BOT_ROOT, _thread_comment("alice", "Not a bug.", is_bot=True)],
            _rejected(),
            "REFUSED",
            id="a-bot-with-the-authors-login-replied",
        ),
        pytest.param(
            [_thread_comment("alice", _FINDING, is_bot=True), _AUTHOR_REPLY],
            _rejected(),
            "REFUSED",
            id="bot-thread-opened-by-the-pr-author",
        ),
    ],
)
def test_author_rejected_bot_finding_resolves_only_when_the_judge_upholds_it(
    monkeypatch, tmp_path: Path, comments: list[dict], rejected: dict, expected: str
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    base_sha = _commit(tmp_path, "CACHE = {}\n")
    head_sha = _commit(tmp_path, "CACHE = {'warm': True}\n\ndef handler():\n    return CACHE['warm']\n")
    monkeypatch.setattr(review_pr, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review_local, "REPO_ROOT", tmp_path)
    _JudgingReviewer.facts = {
        "risky_areas": [],
        "reviews_on_current_head": [],
        "owning_team_author": False,
        "strong_familiarity": False,
        "unresolved_substantive_concerns": [],
        "other_refusal_grounds": [],
        "rejected_bot_concerns": [rejected],
        "reasoning": "One rejected finding.",
        "change_summary": "The handler reads from a warm cache.",
    }
    monkeypatch.setattr(openai_reviewer, "OpenAIReviewer", _JudgingReviewer)
    context = {
        "repo": "PostHog/posthog",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_base_sha": base_sha,
        "commit_messages": ["chore: change the handler"],
        "pr": {
            "number": 1,
            "title": "chore(app): warm the handler cache",
            "state": "OPEN",
            "mergeable_state": "clean",
            "user": {"login": "alice", "type": "User"},
        },
        "check_runs": [],
        "review_threads": [
            {"is_resolved": False, "is_outdated": False, "path": "src/app.py", "line": 3, "comments": comments}
        ],
    }

    result = review_local.run(context)

    assert result["final_verdict"] == expected
    upheld = f"after checking the author's rejection: `posthog`: {_FINDING} Rejection holds:"
    assert (upheld in result["review_body"]) is (expected == "APPROVED")
    assert ".." not in result["review_body"]


def _graphql_comment(login: str, typename: str, association: str, reply_to: dict | None) -> dict:
    return {
        "author": {"login": login, "__typename": typename},
        "authorAssociation": association,
        "body": _FINDING if reply_to is None else f"Not a bug, says {login}.",
        "databaseId": 1,
        "replyTo": reply_to,
        "reactions": {"nodes": []},
    }


@pytest.mark.parametrize(
    "replies, expected",
    [
        pytest.param([("alice", "User", "MEMBER")], "APPROVED", id="author-answered-the-bot"),
        pytest.param(
            [("alice", "User", "MEMBER"), ("mallory", "User", "NONE")], "REFUSED", id="an-untrusted-person-joined"
        ),
    ],
)
def test_fetched_bot_thread_resolves_only_between_the_bot_and_the_author(
    monkeypatch, tmp_path: Path, replies: list[tuple[str, str, str]], expected: str
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    base_sha = _commit(tmp_path, "CACHE = {}\n")
    head_sha = _commit(tmp_path, "CACHE = {'warm': True}\n\ndef handler():\n    return CACHE['warm']\n")
    monkeypatch.setattr(review_pr, "REPO_ROOT", tmp_path)
    pull = {
        "title": "chore(app): warm the handler cache",
        "state": "open",
        "draft": False,
        "mergeable_state": "clean",
        "user": {"login": "alice", "type": "User"},
        "labels": [],
        "body": "",
        "base": {"ref": "master", "sha": base_sha, "repo": {"default_branch": "master"}},
        "head": {"sha": head_sha},
    }
    rest = {"repos/PostHog/posthog/pulls/1": pull, f"repos/PostHog/posthog/commits/{head_sha}/check-runs": {}}
    monkeypatch.setattr(github, "_gh_api", lambda endpoint, paginate=False: rest.get(endpoint, []))
    nodes = [_graphql_comment("posthog", "Bot", "NONE", None)] + [
        _graphql_comment(*reply, {"databaseId": 1}) for reply in replies
    ]
    thread = {"isResolved": False, "isOutdated": False, "path": "src/app.py", "line": 3}
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
    graphql = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reactions": {"nodes": []},
                    "reviewThreads": {
                        **page,
                        "nodes": [{**thread, "comments": {"pageInfo": {"hasNextPage": False}, "nodes": nodes}}],
                    },
                }
            }
        }
    }
    monkeypatch.setattr(github, "_gh_graphql", lambda query, variables=None: graphql)
    monkeypatch.setattr(github, "_is_org_member", lambda org, member: False)
    monkeypatch.setattr(familiarity, "_fetch_author_pr_numbers", lambda author, repo: set())
    _JudgingReviewer.facts = {
        "risky_areas": [],
        "reviews_on_current_head": [],
        "owning_team_author": False,
        "strong_familiarity": False,
        "unresolved_substantive_concerns": [],
        "other_refusal_grounds": [],
        "rejected_bot_concerns": [_rejected()],
        "reasoning": "One rejected finding.",
        "change_summary": "The handler reads from a warm cache.",
    }
    monkeypatch.setattr(openai_reviewer, "OpenAIReviewer", _JudgingReviewer)

    pipeline = review_pr.Pipeline(1, "PostHog/posthog")
    pipeline.run()
    result = pipeline.to_dict()

    assert result["final_verdict"] == expected
    upheld = f"after checking the author's rejection: `posthog`: {_FINDING} Rejection holds:"
    assert (upheld in result["review_body"]) is (expected == "APPROVED")
