"""Realistic GitHub ``pull_request`` webhook payloads + HMAC signing for the harness.

Only the fields the stamphog webhook path and review context actually read are populated
(the real GitHub payload has hundreds more). Shapes match what ``tasks/tasks.py`` and the
review activities consume: installation.id, repository.full_name, and the pull_request
subtree (number, title, body, html_url, user.login, head/base shas, merge facts).
"""

from __future__ import annotations

import hmac
import json
import hashlib
from typing import Any


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
) -> dict[str, Any]:
    """Assemble one ``pull_request`` webhook body for ``action`` (opened/synchronize/closed)."""
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
            "user": {"login": author_login},
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


def sign_payload(body: bytes, secret: str) -> str:
    """Compute the ``X-Hub-Signature-256`` header value GitHub would send for ``body``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def encode(payload: dict[str, Any]) -> bytes:
    """Serialize a payload the same way the client body is sent, so the HMAC matches."""
    return json.dumps(payload).encode("utf-8")
