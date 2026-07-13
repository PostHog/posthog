"""GitHub fake installed at the egress seam (``github_request``).

``StamphogGitHubClient`` funnels every outbound call through
``posthog.egress.github.transport.github_request``. The harness patches that reference
(as imported into ``logic/github_client``) with ``GitHubRecorder.github_request`` and stubs
the two limiter helpers that inspect a real ``requests.Response``. The recorder serves
scripted reads keyed by (method, path) and records every write (approve review, sticky
comment) into ``github_writes`` with its body, returning plausible GitHub response JSON.
"""

from __future__ import annotations

import re
from typing import Any

# Path shapes we route on. Kept as compiled patterns so routing stays readable.
_TOKEN_RE = re.compile(r"^/app/installations/(?P<inst>[^/]+)/access_tokens$")
_PR_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)$")
_PR_FILES_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/files$")
_REVIEWS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/reviews$")
_ISSUE_COMMENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/comments$")
_COMMENT_PATCH_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/comments/(?P<cid>\d+)$")
_CONTENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/contents/(?P<path>.+)$")

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

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class GitHubRecorder:
    """Scriptable GitHub API fake. Configure reads, then read ``github_writes`` after a run."""

    def __init__(self) -> None:
        # Scripted read state, all keyed by their natural identity.
        self.prs: dict[tuple[str, int], dict] = {}
        self.pr_files: dict[tuple[str, int], list[dict]] = {}
        self.author_merged: dict[tuple[str, str], list[int]] = {}
        self.teams_by_login: dict[str, list[str]] = {}
        self.policy_files: dict[str, str] = {}
        # Recorded writes (approve reviews + issue comments), each {method, repo, number, body}.
        self.github_writes: list[dict[str, Any]] = []
        self._next_id = 90000

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def register_pr(self, repo: str, number: int, pr_object: dict, files: list[dict] | None = None) -> None:
        self.prs[(repo, number)] = pr_object
        self.pr_files[(repo, number)] = files if files is not None else []

    def github_request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Drop-in for ``github_request`` — route by (method, path), record writes."""
        path = url[len(_API_PREFIX) :] if url.startswith(_API_PREFIX) else url
        json_body = kwargs.get("json")
        params = kwargs.get("params") or {}

        if method == "POST" and (m := _TOKEN_RE.match(path)):
            return self._mint_token(m.group("inst"))
        if method == "GET" and (m := _PR_FILES_RE.match(path)):
            return self._get_files(m.group("repo"), int(m.group("number")), params)
        if method == "GET" and (m := _PR_RE.match(path)):
            return self._get_pr(m.group("repo"), int(m.group("number")))
        if method == "GET" and path == "/search/issues":
            return self._search_issues(params)
        if method == "GET" and (m := _CONTENTS_RE.match(path)):
            return self._get_contents(m.group("path"))
        if method == "POST" and path == "/graphql":
            return self._graphql(json_body or {})
        if method == "POST" and (m := _REVIEWS_RE.match(path)):
            return self._record_write("approve_review", m.group("repo"), int(m.group("number")), json_body)
        if method == "GET" and _ISSUE_COMMENTS_RE.match(path):
            # Sticky-comment lookup: no existing stamphog comment, so upsert posts a new one.
            return FakeResponse(200, json_data=[])
        if method == "POST" and (m := _ISSUE_COMMENTS_RE.match(path)):
            return self._record_write("issue_comment", m.group("repo"), int(m.group("number")), json_body)
        if method == "PATCH" and (m := _COMMENT_PATCH_RE.match(path)):
            return self._record_write("issue_comment_edit", m.group("repo"), 0, json_body)

        raise AssertionError(f"fake github: unrouted {method} {path}")

    def _mint_token(self, installation_id: str) -> FakeResponse:
        # One hour out, matching GitHub's installation-token lifetime.
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
        # Single page: return the scripted files on page 1, empty thereafter.
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

    def _get_contents(self, path: str) -> FakeResponse:
        content = self.policy_files.get(path)
        if content is None:
            return FakeResponse(404, text="not found")
        return FakeResponse(200, text=content, headers={"Content-Type": "text/plain; charset=utf-8"})

    def _graphql(self, body: dict) -> FakeResponse:
        login = str(((body.get("variables") or {}).get("login")) or "")
        slugs = self.teams_by_login.get(login, [])
        data = {"data": {"organization": {"teams": {"nodes": [{"slug": s} for s in slugs]}}}}
        return FakeResponse(200, json_data=data)

    def _record_write(self, kind: str, repo: str, number: int, body: dict | None) -> FakeResponse:
        new_id = self._alloc_id()
        self.github_writes.append({"kind": kind, "repo": repo, "number": number, "body": body or {}, "id": new_id})
        return FakeResponse(201 if kind != "issue_comment_edit" else 200, json_data={"id": new_id})


def _extract(query: str, prefix: str) -> str:
    """Pull the token following ``prefix`` out of a GitHub search query string."""
    for token in query.split():
        if token.startswith(prefix):
            return token[len(prefix) :]
    return ""


def noop_remember_observed_core_limit(*args: Any, **kwargs: Any) -> None:
    """Stub for the limiter's response inspector — the fake response has no rate headers."""
    return None


def noop_raise_if_github_rate_limited(*args: Any, **kwargs: Any) -> None:
    """Stub for the rate-limit guard — the fake never rate-limits."""
    return None
