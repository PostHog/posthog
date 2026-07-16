"""Replay pending GitHub mentions when a user connects (or re-scopes) their personal GitHub.

The connect-gate records a mention it couldn't run yet as a ``GitHubPendingMention`` keyed on the
commenter's immutable GitHub account id. When that account connects a personal GitHub integration,
the connect callbacks enqueue this task, which re-runs every still-pending mention from the last 12
hours through the normal processing path (so org membership and repo scope are re-checked). Older
rows expire silently. The account-id key is what makes the replay binding verified — the OAuth flow
that just ran proves the connecting user controls that account.
"""

from datetime import timedelta
from typing import Any, cast

from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.github_mention.process import process_github_mention
from products.signals.backend.models import GitHubPendingMention

logger = structlog.get_logger(__name__)

_REPLAY_WINDOW = timedelta(hours=12)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def replay_github_pending_mentions(*, user_id: int, github_account_id: int) -> None:
    """Re-run this account's still-pending mentions from the last 12h; expire the rest.

    Uses ``all_teams`` deliberately: a user's pending mentions can span multiple orgs, so the replay
    is genuinely cross-team, keyed on the GitHub account id rather than one team.
    """
    now = timezone.now()
    cutoff = now - _REPLAY_WINDOW

    expired = GitHubPendingMention.all_teams.filter(
        github_account_id=github_account_id,
        status=GitHubPendingMention.Status.PENDING,
        created_at__lt=cutoff,
    ).update(status=GitHubPendingMention.Status.SKIPPED_EXPIRED, processed_at=now)

    replayed = 0
    pending = GitHubPendingMention.all_teams.filter(
        github_account_id=github_account_id,
        status=GitHubPendingMention.Status.PENDING,
        created_at__gte=cutoff,
    )
    for row in pending:
        cast(Any, process_github_mention).delay(
            team_id=row.team_id,
            pr_url=row.pr_url,
            repository=row.repository,
            comment_id=row.comment_id,
            commenter_account_id=github_account_id,
            commenter_login=row.github_login,
            installation_id=row.installation_id,
        )
        row.status = GitHubPendingMention.Status.PROCESSED
        row.processed_at = now
        row.save(update_fields=["status", "processed_at"])
        replayed += 1

    if replayed or expired:
        logger.info(
            "github_mention_replay",
            user_id=user_id,
            github_account_id=github_account_id,
            replayed=replayed,
            expired=expired,
        )
