"""Reusable GitHub, Slack, and sandbox fakes for the stamphog integration tests.

The chain has exactly four true boundaries; each fake stands in at one of them:
  * GitHub  — the egress transport ``github_request`` (``GitHubRecorder``)
  * Slack   — the ``SlackIntegration`` client (``FakeSlackIntegration``)
  * Sandbox — ``get_sandbox_class_for_backend`` (``make_fake_sandbox_class``)
  * LLM     — patched to raise so the digest uses its deterministic fallback

Everything else in the chain (webhook view, Celery task, review activities, ORM,
audience / channel-resolution / digest logic) runs as real code. The dev runner
(``dev/run_scenario.py``) reuses these same fakes against a real sandbox.
"""

from __future__ import annotations

import re
import hmac
import json
import hashlib
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from slack_sdk.errors import SlackApiError

# --- Webhook payload + signing (mirrors what GitHub sends) ---

_RELEVANT_PR_FIELDS = ("number", "title", "body")


def build_pull_request_event(
    *,
    action: str,
    installation_id: str,
    repo: str,
    number: int,
    title: str,
    body: str,
    author_login: str,
    head_sha: str,
    head_ref: str,
    base_sha: str,
    merged: bool = False,
    merged_at: str | None = None,
    merge_commit_sha: str = "",
    additions: int = 0,
    deletions: int = 0,
    changed_files: int = 0,
    draft: bool = False,
    author_association: str = "MEMBER",
    user_type: str = "User",
) -> dict[str, Any]:
    """Assemble one ``pull_request`` webhook body for ``action`` (opened/synchronize/closed).

    Defaults to a trusted-member, non-bot, non-draft PR so the review path proceeds; override
    ``author_association`` / ``user_type`` / ``draft`` to exercise the pre-sandbox skips.
    """
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "pull_request": {
            "number": number,
            "title": title,
            "body": body,
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "state": "closed" if action == "closed" else "open",
            "draft": draft,
            "author_association": author_association,
            "user": {"login": author_login, "type": user_type},
            "head": {"sha": head_sha, "ref": head_ref},
            "base": {"sha": base_sha, "ref": "master"},
            "merged": merged,
            "merged_at": merged_at,
            "merge_commit_sha": merge_commit_sha,
            "additions": additions,
            "deletions": deletions,
            "changed_files": changed_files,
        },
    }


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def sign_payload(body: bytes, secret: str) -> str:
    """Compute the ``X-Hub-Signature-256`` header GitHub would send for ``body``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# --- GitHub fake at the egress seam (``github_request``) ---

_TOKEN_RE = re.compile(r"^/app/installations/(?P<inst>[^/]+)/access_tokens$")
_PR_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)$")
_PR_FILES_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/files$")
_PR_COMMITS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/commits$")
_REVIEWS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/reviews$")
_ISSUE_COMMENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/comments$")
_COMMENT_PATCH_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/comments/(?P<cid>\d+)$")
_DISMISS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/reviews/(?P<rid>\d+)/dismissals$")
_LABEL_DELETE_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/labels/(?P<label>[^/]+)$")
_LABEL_ADD_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/labels$")
_CONTENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/contents/(?P<path>.+)$")
_CHECK_RUNS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/commits/(?P<sha>[^/]+)/check-runs$")
_COLLABORATOR_PERMISSION_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/collaborators/(?P<username>[^/]+)/permission$")
_PR_REACTIONS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/reactions$")
_COMPARE_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/compare/(?P<basehead>[^/]+)$")
_PR_REACTION_DELETE_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/reactions/(?P<rid>\d+)$")

_API_PREFIX = "https://api.github.com"


class FakeResponse:
    """Minimal ``requests.Response`` stand-in — only what the client touches."""

    def __init__(
        self, status_code: int, *, json_data: Any = None, text: str = "", headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text if text else ("" if json_data is None else "<json>")
        self.headers = headers or {}
        self.encoding = "utf-8"

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size: int = 8192) -> Iterable[bytes]:
        raw = (json.dumps(self._json) if self._json is not None else self.text).encode()
        for start in range(0, len(raw), chunk_size):
            yield raw[start : start + chunk_size]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class GitHubRecorder:
    """Scriptable GitHub API fake. Configure reads, then read ``github_writes`` after a run."""

    def __init__(self) -> None:
        self.prs: dict[tuple[str, int], dict] = {}
        self.pr_files: dict[tuple[str, int], list[dict]] = {}
        self.pr_reviews: dict[tuple[str, int], list[dict]] = {}
        # (repo, number) -> GraphQL reviewThreads node dicts for get_pr_review_threads; default none.
        self.review_threads: dict[tuple[str, int], list[dict]] = {}
        # Pre-existing issue comments a GET returns (e.g. a user-planted sticky marker to exercise the
        # bot-identity filter in upsert_sticky_comment). Empty by default — most tests post fresh.
        self.issue_comments: dict[tuple[str, int], list[dict]] = {}
        self.author_merged: dict[tuple[str, str], list[int]] = {}
        # (repo, login) -> permission for the author write gate; unscripted authors default to "write"
        # so tests that aren't about the gate flow through it.
        self.collaborator_permissions: dict[tuple[str, str], str] = {}
        # (repo, number) -> raw reaction dicts for the in-flight reviewer-bot wait; default none.
        self.pr_reactions: dict[tuple[str, int], list[dict]] = {}
        # (repo, number) -> id of the reaction stamphog's own add_pr_reaction posted, so a repeat POST
        # returns the same id (GitHub's real idempotency) and a DELETE has something to clear.
        self._own_reactions: dict[tuple[str, int], int] = {}
        # Test hook: force every reaction POST to return this response (e.g. a 500) to
        # exercise the client's fail-open path without monkeypatching bound methods.
        self.reaction_response_override: FakeResponse | None = None
        # Test hook: force every label-add POST to return this response (e.g. a 422 for a label that
        # does not exist on the repo) to exercise the handoff's best-effort swallow path.
        self.add_label_response_override: FakeResponse | None = None
        # Test hook: raise this exception from the label-add POST (e.g. GitHubRateLimitError) to
        # exercise the best-effort catch for exception types the client does not raise itself.
        self.add_label_side_effect: Exception | None = None
        # Set to make posting a COMMENT review blow up, e.g. a rate limit on the failure notice.
        self.comment_review_side_effect: Exception | None = None
        self.teams_by_login: dict[str, list[str]] = {}
        # The merge base the compare API reports for every PR, and the familiarity GraphQL answers:
        # path -> blame ranges, and path -> the author's history nodes. Unscripted paths answer empty.
        self.merge_base_sha = "mergebase000"
        # (repo, number) -> the PR's commits, oldest first. register_pr fills one commit at the head.
        self.pr_commits: dict[tuple[str, int], list[dict]] = {}
        self.blame_ranges: dict[str, list[dict]] = {}
        self.author_history: dict[str, list[dict]] = {}
        self.policy_files: dict[str, str] = {}
        # Per-repository overrides for the same paths, for cases where two connected repos must
        # answer differently (one carries a root owners.yaml, another does not).
        self.repo_files: dict[tuple[str, str], str] = {}
        # Repositories with no commits at all. GitHub answers their head lookup with a null
        # defaultBranchRef, which is what a freshly created connected repo looks like.
        self.empty_repositories: set[str] = set()
        self.github_writes: list[dict[str, Any]] = []
        self._next_id = 90000

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def register_pr(
        self,
        repo: str,
        number: int,
        pr_object: dict,
        files: list[dict] | None = None,
        commit_messages: tuple[str, ...] = ("feat: change",),
    ) -> None:
        self.prs[(repo, number)] = pr_object
        self.pr_files[(repo, number)] = files if files is not None else []
        head_sha = (pr_object.get("head") or {}).get("sha") or ""
        shas = [f"{head_sha}-parent{index}" for index in range(len(commit_messages) - 1)] + [head_sha]
        self.pr_commits[(repo, number)] = [
            {"sha": sha, "commit": {"message": message}} for sha, message in zip(shas, commit_messages)
        ]

    def github_request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Drop-in for ``github_request`` — route by (method, path), record writes."""
        path = url[len(_API_PREFIX) :] if url.startswith(_API_PREFIX) else url
        json_body = kwargs.get("json")
        params = kwargs.get("params") or {}

        if method == "POST" and (m := _TOKEN_RE.match(path)):
            return self._mint_token(m.group("inst"))
        if method == "GET" and (m := _PR_FILES_RE.match(path)):
            return self._get_files(m.group("repo"), int(m.group("number")), params)
        if method == "GET" and (m := _PR_COMMITS_RE.match(path)):
            page = int(params.get("page", 1))
            commits = self.pr_commits.get((m.group("repo"), int(m.group("number"))), []) if page == 1 else []
            return FakeResponse(200, json_data=commits)
        if method == "GET" and (m := _PR_RE.match(path)):
            return self._get_pr(m.group("repo"), int(m.group("number")))
        if method == "GET" and path == "/search/issues":
            return self._search_issues(params)
        if method == "GET" and _COMPARE_RE.match(path):
            return FakeResponse(200, json_data={"merge_base_commit": {"sha": self.merge_base_sha}})
        if method == "GET" and _CHECK_RUNS_RE.match(path):
            return FakeResponse(200, json_data={"check_runs": []})
        if method == "GET" and (m := _COLLABORATOR_PERMISSION_RE.match(path)):
            permission = self.collaborator_permissions.get((m.group("repo"), m.group("username")), "write")
            return FakeResponse(200, json_data={"permission": permission})
        if method == "GET" and (m := _PR_REACTIONS_RE.match(path)):
            page = int(params.get("page", 1))
            per_page = int(params.get("per_page", 30))
            items = self.pr_reactions.get((m.group("repo"), int(m.group("number"))), [])
            return FakeResponse(200, json_data=items[per_page * (page - 1) : per_page * page])
        if method == "POST" and (m := _PR_REACTIONS_RE.match(path)):
            return self._add_reaction(m.group("repo"), int(m.group("number")), json_body)
        if method == "DELETE" and (m := _PR_REACTION_DELETE_RE.match(path)):
            return self._remove_reaction(m.group("repo"), int(m.group("number")), int(m.group("rid")))
        if method == "GET" and (m := _CONTENTS_RE.match(path)):
            return self._get_contents(m.group("repo"), m.group("path"))
        if method == "POST" and path == "/graphql":
            return self._graphql(json_body or {})
        if method == "GET" and (m := _REVIEWS_RE.match(path)):
            return FakeResponse(200, json_data=self.pr_reviews.get((m.group("repo"), int(m.group("number"))), []))
        if method == "POST" and (m := _REVIEWS_RE.match(path)):
            # Split by event so a test asserting on approvals never matches a COMMENT review.
            event = (json_body or {}).get("event")
            kind = "approve_review" if event == "APPROVE" else "comment_review"
            if kind == "comment_review" and self.comment_review_side_effect is not None:
                raise self.comment_review_side_effect
            return self._record_write(kind, m.group("repo"), int(m.group("number")), json_body)
        if method == "GET" and (m := _ISSUE_COMMENTS_RE.match(path)):
            page = int(params.get("page", 1))
            comments = self.issue_comments.get((m.group("repo"), int(m.group("number"))), []) if page == 1 else []
            return FakeResponse(200, json_data=comments)
        if method == "POST" and (m := _ISSUE_COMMENTS_RE.match(path)):
            return self._record_write("issue_comment", m.group("repo"), int(m.group("number")), json_body)
        if method == "PATCH" and (m := _COMMENT_PATCH_RE.match(path)):
            return self._record_write("issue_comment_edit", m.group("repo"), 0, json_body)
        if method == "PUT" and (m := _DISMISS_RE.match(path)):
            return self._dismiss_review(m.group("repo"), int(m.group("number")), int(m.group("rid")), json_body)
        if method == "POST" and (m := _LABEL_ADD_RE.match(path)):
            return self._add_label(m.group("repo"), int(m.group("number")), json_body)
        if method == "DELETE" and (m := _LABEL_DELETE_RE.match(path)):
            return self._remove_label(m.group("repo"), int(m.group("number")), m.group("label"))

        raise AssertionError(f"fake github: unrouted {method} {path}")

    def _mint_token(self, installation_id: str) -> FakeResponse:
        return FakeResponse(
            201,
            json_data={"token": f"ghs_fake_{installation_id}", "expires_at": "2999-01-01T00:00:00Z"},
        )

    def _get_pr(self, repo: str, number: int) -> FakeResponse:
        pr = self.prs.get((repo, number))
        if pr is None:
            return FakeResponse(404, text="not found")
        return FakeResponse(200, json_data=pr)

    def _get_files(self, repo: str, number: int, params: dict) -> FakeResponse:
        page = int(params.get("page", 1))
        files = self.pr_files.get((repo, number), []) if page == 1 else []
        return FakeResponse(200, json_data=files)

    def _search_issues(self, params: dict) -> FakeResponse:
        query = str(params.get("q", ""))
        repo = _extract(query, "repo:")
        author = _extract(query, "author:")
        page = int(params.get("page", 1))
        numbers = self.author_merged.get((repo, author), []) if page == 1 else []
        return FakeResponse(200, json_data={"items": [{"number": n} for n in numbers]})

    def _get_contents(self, repo: str, path: str) -> FakeResponse:
        content = self.repo_files.get((repo, path), self.policy_files.get(path))
        if content is None:
            return FakeResponse(404, text="not found")
        return FakeResponse(200, text=content, headers={"Content-Type": "text/plain; charset=utf-8"})

    def _graphql(self, body: dict) -> FakeResponse:
        query = str(body.get("query") or "")
        variables = body.get("variables") or {}
        # GraphQL callers share /graphql: get_pr_review_threads, get_user_team_slugs, the familiarity
        # blame and history reads, the minimizeComment mutation after a dismissal, and the shared
        # ownership file reader. Route by the query's shape.
        if "blame(" in query:
            ranges = self.blame_ranges.get(str(variables.get("path")), [])
            return FakeResponse(200, json_data={"data": {"repository": {"object": {"blame": {"ranges": ranges}}}}})
        if "history(" in query:
            aliases = {
                name: {"nodes": self.author_history.get(str(path), [])}
                for name, path in variables.items()
                if re.fullmatch(r"p\d+", name)
            }
            return FakeResponse(200, json_data={"data": {"repository": {"object": aliases}}})
        if "minimizeComment" in query:
            self.github_writes.append({"kind": "minimize_review", "node_id": variables.get("id"), "query": query})
            return FakeResponse(
                200, json_data={"data": {"minimizeComment": {"minimizedComment": {"isMinimized": True}}}}
            )
        if "defaultBranchRef" in query:
            if f"{variables.get('owner', '')}/{variables.get('name', '')}" in self.empty_repositories:
                return FakeResponse(200, json_data={"data": {"repository": {"defaultBranchRef": None}}})
            # The ownership reader caches blobs per commit, and the cache outlives one test. A commit
            # derived from the scripted files keeps each test reading its own files.
            scripted = repr(sorted(self.policy_files.items()) + sorted(self.repo_files.items()))
            oid = hashlib.sha256(scripted.encode()).hexdigest()
            return FakeResponse(200, json_data={"data": {"repository": {"defaultBranchRef": {"target": {"oid": oid}}}}})
        if "object(expression:" in query:
            return self._ownership_blobs(f"{variables.get('owner', '')}/{variables.get('name', '')}", query, variables)
        if "reviewThreads" in query:
            repo = f"{variables.get('owner', '')}/{variables.get('name', '')}"
            number = int(variables.get("pr") or 0)
            nodes = self.review_threads.get((repo, number), [])
            data = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
                        }
                    }
                }
            }
            return FakeResponse(200, json_data=data)
        login = str(variables.get("login") or "")
        slugs = self.teams_by_login.get(login, [])
        teams_data = {"data": {"organization": {"teams": {"nodes": [{"slug": s} for s in slugs]}}}}
        return FakeResponse(200, json_data=teams_data)

    def _ownership_blobs(self, repo: str, query: str, variables: dict) -> FakeResponse:
        """The aliased blob lookups the shared ownership reader sends, served from the same files the
        contents API answers with. Each variable holds a ``<commit>:<path>`` expression."""
        field: dict[str, Any] = {}
        for name, expression in variables.items():
            if name in ("owner", "name"):
                continue
            path = str(expression).split(":", 1)[1]
            content = self.repo_files.get((repo, path), self.policy_files.get(path))
            if content is None:
                field[f"f{name[1:]}"] = None
            else:
                field[f"f{name[1:]}"] = {"text": content} if "text" in query else {"__typename": "Blob"}
        return FakeResponse(200, json_data={"data": {"repository": field}})

    def _record_write(self, kind: str, repo: str, number: int, body: dict | None) -> FakeResponse:
        new_id = self._alloc_id()
        self.github_writes.append({"kind": kind, "repo": repo, "number": number, "body": body or {}, "id": new_id})
        return FakeResponse(201 if kind != "issue_comment_edit" else 200, json_data={"id": new_id})

    def _add_reaction(self, repo: str, number: int, body: dict | None) -> FakeResponse:
        """Mirror GitHub's real idempotency: a repeat POST with the same identity returns 200 + the
        existing id instead of stacking a second reaction; only the first POST is a 201 creation."""
        if self.reaction_response_override is not None:
            return self.reaction_response_override
        content = (body or {}).get("content", "")
        key = (repo, number)
        existing_id = self._own_reactions.get(key)
        if existing_id is not None:
            return FakeResponse(200, json_data={"id": existing_id, "content": content})
        new_id = self._alloc_id()
        self._own_reactions[key] = new_id
        self.github_writes.append(
            {"kind": "add_reaction", "repo": repo, "number": number, "content": content, "id": new_id}
        )
        return FakeResponse(201, json_data={"id": new_id, "content": content})

    def _remove_reaction(self, repo: str, number: int, reaction_id: int) -> FakeResponse:
        key = (repo, number)
        if self._own_reactions.get(key) == reaction_id:
            del self._own_reactions[key]
        self.github_writes.append(
            {"kind": "remove_reaction", "repo": repo, "number": number, "reaction_id": reaction_id}
        )
        return FakeResponse(204)

    def _remove_label(self, repo: str, number: int, label: str) -> FakeResponse:
        self.github_writes.append({"kind": "remove_label", "repo": repo, "number": number, "label": label})
        return FakeResponse(200, json_data=[])

    def _add_label(self, repo: str, number: int, body: dict | None) -> FakeResponse:
        labels = (body or {}).get("labels", [])
        self.github_writes.append({"kind": "add_label", "repo": repo, "number": number, "labels": labels})
        # A side effect set by the test simulates the egress layer raising before the response is
        # returned — a GitHubRateLimitError (the real raise_if_github_rate_limited is stubbed to a
        # no-op in the chain, so the rate-limit path is otherwise unreachable in tests) or a
        # requests.RequestException on a network blip. Exercises the handoff's best-effort catch.
        if self.add_label_side_effect is not None:
            raise self.add_label_side_effect
        if self.add_label_response_override is not None:
            return self.add_label_response_override
        return FakeResponse(200, json_data=[{"name": n} for n in labels])

    def _dismiss_review(self, repo: str, number: int, review_id: int, body: dict | None) -> FakeResponse:
        self.github_writes.append(
            {"kind": "dismiss_review", "repo": repo, "number": number, "review_id": review_id, "body": body or {}}
        )
        # Reflect the dismissal in the reviews list like real GitHub does (state -> DISMISSED), so a
        # subsequent get_pr_reviews / list_own_active_approvals no longer sees it as active.
        for review in self.pr_reviews.get((repo, number), []):
            if review.get("id") == review_id:
                review["state"] = "DISMISSED"
        return FakeResponse(200, json_data={"id": review_id, "node_id": f"PRR_{review_id}", "state": "DISMISSED"})


def _extract(query: str, prefix: str) -> str:
    for token in query.split():
        if token.startswith(prefix):
            return token[len(prefix) :]
    return ""


def review_thread_node(
    *,
    path: str,
    comments: list[tuple[str, str]],
    is_resolved: bool = False,
    is_outdated: bool = False,
    line: int | None = 1,
    author_association: str = "MEMBER",
    author_typename: str = "User",
    comments_have_next_page: bool = False,
    thread_id: str = "RT_1",
) -> dict[str, Any]:
    """Build one GraphQL reviewThreads node (what get_pr_review_threads parses), from (author, body) pairs."""
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "path": path,
        "line": line,
        "comments": {
            "pageInfo": {"hasNextPage": comments_have_next_page, "endCursor": "cc"},
            "nodes": [
                {
                    "author": {"login": author, "__typename": author_typename},
                    "authorAssociation": author_association,
                    "body": body,
                }
                for author, body in comments
            ],
        },
    }


def noop_remember_observed_core_limit(*args: Any, **kwargs: Any) -> None:
    """The limiter's response inspector — the fake response carries no rate headers."""
    return None


def noop_raise_if_github_rate_limited(*args: Any, **kwargs: Any) -> None:
    """The rate-limit guard — the fake never rate-limits."""
    return None


# --- Slack fake at the ``SlackIntegration`` seam ---


class FakeSlackClient:
    """Records ``chat_postMessage`` calls; returns a Slack-shaped ``{"ok", "ts"}``.

    A channel in ``needs_join`` rejects the post with ``not_in_channel`` until ``conversations_join``
    lands, which is what Slack does for a public channel the app was never invited to.
    """

    def __init__(
        self, posted: list[dict[str, Any]], needs_join: set[str], joined: list[str], fail_thread_replies: bool
    ) -> None:
        self._posted = posted
        self._needs_join = needs_join
        self._joined = joined
        self._fail_thread_replies = fail_thread_replies

    def chat_postMessage(self, *, channel: str, blocks: list[dict], text: str, **kwargs: Any) -> dict[str, Any]:
        if channel in self._needs_join and channel not in self._joined:
            raise SlackApiError("not_in_channel", {"ok": False, "error": "not_in_channel"})
        thread_ts = kwargs.get("thread_ts")
        self._posted.append({"channel": channel, "blocks": blocks, "text": text, "thread_ts": thread_ts})
        if thread_ts and self._fail_thread_replies:
            raise SlackApiError("msg_too_long", {"ok": False, "error": "msg_too_long"})
        return {"ok": True, "ts": "1234.5678"}

    def conversations_join(self, *, channel: str) -> dict[str, Any]:
        self._joined.append(channel)
        return {"ok": True}


class FakeSlackIntegration:
    """Stand-in for ``posthog.models.integration.slack.SlackIntegration``.

    Class-level state is shared across every instance a run constructs, so a test can read
    ``posted_messages`` and script ``workspace_channels`` regardless of which module built the
    instance (both the digest-post and channel-resolution paths construct their own).
    """

    posted_messages: list[dict[str, Any]] = []
    workspace_channels: list[dict[str, str]] = []
    # Channels the app has not been invited to, and the ones it joined by itself during the run.
    channels_needing_join: set[str] = set()
    joined_channels: list[str] = []
    # Makes the threaded reply fail while the lead still succeeds, which is the only Slack failure
    # the digest is expected to swallow.
    fail_thread_replies: bool = False

    def __init__(self, integration: Any, *, source: str = "integration") -> None:
        self.integration = integration

    @property
    def client(self) -> FakeSlackClient:
        return FakeSlackClient(
            FakeSlackIntegration.posted_messages,
            FakeSlackIntegration.channels_needing_join,
            FakeSlackIntegration.joined_channels,
            FakeSlackIntegration.fail_thread_replies,
        )

    def list_channels(self, should_include_private_channels: bool = False, authed_user: str = "") -> list[dict]:
        return sorted(FakeSlackIntegration.workspace_channels, key=lambda c: c["name"])

    def list_public_channels(self) -> list[dict]:
        # The workspace fixture is public channels only, so this matches list_channels. Both exist
        # because callers pick one, and a fake missing the method a caller uses fails as a routing
        # error rather than as the missing stub it is.
        return sorted(FakeSlackIntegration.workspace_channels, key=lambda c: c["name"])

    @classmethod
    def reset(
        cls, channels: list[dict[str, str]], *, needs_join: Iterable[str] = (), fail_thread_replies: bool = False
    ) -> None:
        cls.posted_messages = []
        cls.workspace_channels = list(channels)
        cls.channels_needing_join = set(needs_join)
        cls.joined_channels = []
        cls.fail_thread_replies = fail_thread_replies


# --- Sandbox fake at the ``get_sandbox_class_for_backend`` seam ---


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


def approved_engine_output() -> str:
    """A realistic ``review_pr`` ``to_dict()`` payload — gates pass, final verdict APPROVED.

    Emitted as the reviewer's last stdout line (uv/SDK noise can precede it), which is exactly
    what ``parse_reviewer_output`` scans for.
    """
    payload = {
        "final_verdict": "APPROVED",
        "reviewer": {
            "reasoning": "Small, well-tested change. No policy concerns.",
            "issues": [],
            "change_summary": "Docs gain a setup section and the helper stops throwing on an empty list.",
        },
        "gates": [{"name": "size", "passed": True}, {"name": "deny_list", "passed": True}],
        "classification": {
            "tier": "low_risk",
            "reason": "docs + small logic change",
            "ownership": {"teams": ["@PostHog/team-devex"]},
        },
        "policy": {"version": "1"},
        "review_body": "Approved by stamphog. All deterministic gates passed; change is low risk.",
        "stamphog_version": "test-1.0.0",
    }
    return "uv run: resolved 1 package\n" + json.dumps(payload)


def make_fake_sandbox_class(engine_output: str, write_sink: list[tuple[str, bytes]] | None = None) -> type[Any]:
    """A sandbox class returning ``engine_output`` for the reviewer command, no-ops otherwise.

    ``write_sink``, when given, records every ``write_file`` as ``(path, payload)`` so a test can
    assert what was injected into the checkout (e.g. the default policy files).
    """

    class _FakeSandbox:
        # A test can set this on the class to make teardown blow up (destroy-must-not-mask coverage).
        destroy_error: Exception | None = None
        # A test can set this to make teardown hang until the event is set, or for at most ten
        # seconds, so a caller that waits on teardown fails the test instead of hanging it.
        destroy_blocker: threading.Event | None = None
        # Set once destroy() returns, so a test can tell whether its caller waited for it.
        destroy_returned: bool = False
        # A test can set this to make provisioning blow up, which is the first step of the review's
        # paid phase (retry-boundary coverage).
        create_error: Exception | None = None
        # Every SandboxConfig passed to create(), so a test can assert what the sandbox was given
        # (environment variables, egress allowlist).
        created_configs: list[Any] = []
        # Every command passed to execute(), so a test can assert what ran in the sandbox.
        executed_commands: list[str] = []

        @classmethod
        def create(cls, config: Any) -> _FakeSandbox:
            cls.created_configs.append(config)
            if cls.create_error is not None:
                raise cls.create_error
            return cls()

        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            type(self).executed_commands.append(command)
            stdout = engine_output if "review_local.py" in command else ""
            return FakeExecResult(stdout=stdout, stderr="", exit_code=0)

        def write_file(self, path: str, payload: bytes) -> FakeExecResult:
            if write_sink is not None:
                write_sink.append((path, payload))
            return FakeExecResult(stdout="", stderr="", exit_code=0)

        def destroy(self) -> None:
            if self.destroy_blocker is not None:
                self.destroy_blocker.wait(timeout=10)
            type(self).destroy_returned = True
            if self.destroy_error is not None:
                raise self.destroy_error

    return _FakeSandbox
