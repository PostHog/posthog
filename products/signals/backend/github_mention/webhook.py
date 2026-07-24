"""Detect a bot @-mention on a Signals PR comment and enqueue processing.

Wired into the shared ``github_webhook`` dispatcher as a side effect on ``issue_comment`` events so it
coexists with the Conversations handler. Only mentions that resolve to a Signals-created PR in THIS
region enqueue work; everything else is ignored (Conversations still owns its own routing and
cross-region proxying). Cross-region caveat: if a Signals PR's team lives in a different region than
the one that receives the webhook and Conversations doesn't proxy, that mention is missed — rare, and
deferred (see plan).
"""

import hashlib
from typing import Any, cast

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

import structlog

from products.signals.backend.github_mention.process import process_github_mention
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

_MENTION_DEDUP_KEY_PREFIX = "signals:github_mention:delivery:"
# GitHub redelivers failed webhooks; 1h comfortably covers the retry window without pinning memory.
_MENTION_DEDUP_TTL_SECONDS = 60 * 60

_HANDLED_COMMENT_KEY_PREFIX = "signals:github_mention:handled_comment:"
_HANDLED_COMMENT_TTL_SECONDS = 60 * 60


def mark_comment_handled_directly(comment_id: int) -> None:
    """Record that a comment's run was already triggered directly (from the report-view endpoint), so
    the webhook skips it when GitHub delivers the same user-authored comment — no double-trigger."""
    cache.set(f"{_HANDLED_COMMENT_KEY_PREFIX}{comment_id}", True, _HANDLED_COMMENT_TTL_SECONDS)


def _mentions_bot(body: str) -> bool:
    slug = (getattr(settings, "GITHUB_APP_SLUG", None) or "").strip().lower()
    if not slug:
        return False
    # Matches both "@slug" and "@slug[bot]" (the GitHub App bot login form).
    return f"@{slug}" in body.lower()


def _delivery_id(request: HttpRequest, payload: dict[str, Any]) -> str:
    delivery = request.headers.get("X-GitHub-Delivery")
    if delivery:
        return delivery
    return hashlib.sha256(request.body).hexdigest()[:32]


def handle_github_mention_event(request: HttpRequest, payload: dict[str, Any]) -> None:
    """Enqueue a mention run if this is a bot @-mention on a local Signals PR. Never raises."""
    try:
        if payload.get("action") != "created":
            return
        issue = payload.get("issue") or {}
        if not issue.get("pull_request"):
            return  # a plain issue comment, not a PR
        comment = payload.get("comment") or {}
        if comment.get("performed_via_github_app"):
            return  # our own bot comment — avoid loops
        comment_id = comment.get("id")
        if comment_id is not None and cache.get(f"{_HANDLED_COMMENT_KEY_PREFIX}{comment_id}"):
            return  # the report-view endpoint already triggered this comment's run directly
        if not _mentions_bot(comment.get("body") or ""):
            return

        pr_url = (issue.get("pull_request") or {}).get("html_url")
        repository = (payload.get("repository") or {}).get("full_name")
        if not pr_url or not repository:
            return

        context = tasks_facade.resolve_signal_pr_mention_context(pr_url, repository)
        if context is None:
            return  # not a Signals PR (or it lives in another region) — ignore here

        dedup_key = f"{_MENTION_DEDUP_KEY_PREFIX}{_delivery_id(request, payload)}"
        if not cache.add(dedup_key, True, _MENTION_DEDUP_TTL_SECONDS):
            return  # already enqueued this delivery

        commenter = comment.get("user") or {}
        cast(Any, process_github_mention).delay(
            team_id=context.team_id,
            pr_url=pr_url,
            repository=repository,
            comment_id=comment.get("id"),
            commenter_account_id=commenter.get("id"),
            commenter_login=commenter.get("login") or "",
            installation_id=str((payload.get("installation") or {}).get("id") or ""),
        )
    except Exception:
        logger.exception("github_mention_webhook_failed")
