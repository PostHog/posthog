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
from dataclasses import dataclass
from typing import Any

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
_REVIEWS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/reviews$")
_ISSUE_COMMENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/comments$")
_COMMENT_PATCH_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/comments/(?P<cid>\d+)$")
_DISMISS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/pulls/(?P<number>\d+)/reviews/(?P<rid>\d+)/dismissals$")
_LABEL_DELETE_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/labels/(?P<label>[^/]+)$")
_CONTENTS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/contents/(?P<path>.+)$")
_CHECK_RUNS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/commits/(?P<sha>[^/]+)/check-runs$")
_COLLABORATOR_PERMISSION_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/collaborators/(?P<username>[^/]+)/permission$")
_PR_REACTIONS_RE = re.compile(r"^/repos/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)/reactions$")

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
        self.prs: dict[tuple[str, int], dict] = {}
        self.pr_files: dict[tuple[str, int], list[dict]] = {}
        self.pr_reviews: dict[tuple[str, int], list[dict]] = {}
        # Pre-existing issue comments a GET returns (e.g. a user-planted sticky marker to exercise the
        # bot-identity filter in upsert_sticky_comment). Empty by default — most tests post fresh.
        self.issue_comments: dict[tuple[str, int], list[dict]] = {}
        self.author_merged: dict[tuple[str, str], list[int]] = {}
        # (repo, login) -> permission for the author write gate; unscripted authors default to "write"
        # so tests that aren't about the gate flow through it.
        self.collaborator_permissions: dict[tuple[str, str], str] = {}
        # (repo, number) -> raw reaction dicts for the in-flight reviewer-bot wait; default none.
        self.pr_reactions: dict[tuple[str, int], list[dict]] = {}
        self.teams_by_login: dict[str, list[str]] = {}
        self.policy_files: dict[str, str] = {}
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
        if method == "GET" and (m := _CONTENTS_RE.match(path)):
            return self._get_contents(m.group("path"))
        if method == "POST" and path == "/graphql":
            return self._graphql(json_body or {})
        if method == "GET" and (m := _REVIEWS_RE.match(path)):
            return FakeResponse(200, json_data=self.pr_reviews.get((m.group("repo"), int(m.group("number"))), []))
        if method == "POST" and (m := _REVIEWS_RE.match(path)):
            return self._record_write("approve_review", m.group("repo"), int(m.group("number")), json_body)
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

    def _remove_label(self, repo: str, number: int, label: str) -> FakeResponse:
        self.github_writes.append({"kind": "remove_label", "repo": repo, "number": number, "label": label})
        return FakeResponse(200, json_data=[])

    def _dismiss_review(self, repo: str, number: int, review_id: int, body: dict | None) -> FakeResponse:
        self.github_writes.append(
            {"kind": "dismiss_review", "repo": repo, "number": number, "review_id": review_id, "body": body or {}}
        )
        return FakeResponse(200, json_data={})


def _extract(query: str, prefix: str) -> str:
    for token in query.split():
        if token.startswith(prefix):
            return token[len(prefix) :]
    return ""


def noop_remember_observed_core_limit(*args: Any, **kwargs: Any) -> None:
    """The limiter's response inspector — the fake response carries no rate headers."""
    return None


def noop_raise_if_github_rate_limited(*args: Any, **kwargs: Any) -> None:
    """The rate-limit guard — the fake never rate-limits."""
    return None


# --- Slack fake at the ``SlackIntegration`` seam ---


class FakeSlackClient:
    """Records ``chat_postMessage`` calls; returns a Slack-shaped ``{"ok", "ts"}``."""

    def __init__(self, posted: list[dict[str, Any]]) -> None:
        self._posted = posted

    def chat_postMessage(self, *, channel: str, blocks: list[dict], text: str, **kwargs: Any) -> dict[str, Any]:
        self._posted.append({"channel": channel, "blocks": blocks, "text": text})
        return {"ok": True, "ts": "1234.5678"}


class FakeSlackIntegration:
    """Stand-in for ``posthog.models.integration.SlackIntegration``.

    Class-level state is shared across every instance a run constructs, so a test can read
    ``posted_messages`` and script ``workspace_channels`` regardless of which module built the
    instance (both the digest-post and channel-resolution paths construct their own).
    """

    posted_messages: list[dict[str, Any]] = []
    workspace_channels: list[dict[str, str]] = []

    def __init__(self, integration: Any) -> None:
        self.integration = integration

    @property
    def client(self) -> FakeSlackClient:
        return FakeSlackClient(FakeSlackIntegration.posted_messages)

    def list_channels(self, should_include_private_channels: bool = False, authed_user: str = "") -> list[dict]:
        return sorted(FakeSlackIntegration.workspace_channels, key=lambda c: c["name"])

    @classmethod
    def reset(cls, channels: list[dict[str, str]]) -> None:
        cls.posted_messages = []
        cls.workspace_channels = list(channels)


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
        "reviewer": {"reasoning": "Small, well-tested change. No policy concerns.", "issues": []},
        "gates": [{"name": "size", "passed": True}, {"name": "deny_list", "passed": True}],
        "classification": {"tier": "low_risk", "reason": "docs + small logic change"},
        "policy": {"version": "1"},
        "review_body": "Approved by stamphog. All deterministic gates passed; change is low risk.",
        "stamphog_version": "test-1.0.0",
    }
    return "uv run: resolved 1 package\n" + json.dumps(payload)


def make_fake_sandbox_class(engine_output: str, write_sink: list[tuple[str, bytes]] | None = None) -> type:
    """A sandbox class returning ``engine_output`` for the reviewer command, no-ops otherwise.

    ``write_sink``, when given, records every ``write_file`` as ``(path, payload)`` so a test can
    assert what was injected into the checkout (e.g. the default policy files).
    """

    class _FakeSandbox:
        # A test can set this on the class to make teardown blow up (destroy-must-not-mask coverage).
        destroy_error: Exception | None = None
        # Every SandboxConfig passed to create(), so a test can assert what the sandbox was given
        # (environment variables, egress allowlist).
        created_configs: list[Any] = []

        @classmethod
        def create(cls, config: Any) -> _FakeSandbox:
            cls.created_configs.append(config)
            return cls()

        def execute(self, command: str, timeout_seconds: int | None = None) -> FakeExecResult:
            stdout = engine_output if "review_local.py" in command else ""
            return FakeExecResult(stdout=stdout, stderr="", exit_code=0)

        def write_file(self, path: str, payload: bytes) -> FakeExecResult:
            if write_sink is not None:
                write_sink.append((path, payload))
            return FakeExecResult(stdout="", stderr="", exit_code=0)

        def destroy(self) -> None:
            if self.destroy_error is not None:
                raise self.destroy_error

    return _FakeSandbox
