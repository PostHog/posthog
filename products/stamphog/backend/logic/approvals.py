"""Shared retraction of stale stamphog approvals when a PR's head moves.

GitHub never auto-dismisses an APPROVE review when new commits land, so a prior run's approval at an
old head keeps satisfying required reviews after a push. Two paths must retract it, and they share this
one implementation:
  * the review workflow's dismiss_stale_approvals activity (runs before re-reviewing), and
  * the Celery task's LABEL-mode skip path — a head-changing event whose trigger label is absent never
    enters the workflow, so the standing approval would otherwise survive an unreviewed push.
"""

from __future__ import annotations

from django.utils import timezone

from ..models import PullRequest, ReviewRun, StamphogRepoConfig
from .github_client import StamphogGitHubClient

DEFAULT_DISMISS_MESSAGE = (
    "New commits were pushed — dismissing the stamphog approval from an earlier head; a re-review runs automatically."
)


def dismiss_stale_approvals_for_head(
    team_id: int,
    pull_request: PullRequest,
    repo_config: StamphogRepoConfig,
    current_head_sha: str,
    message: str = DEFAULT_DISMISS_MESSAGE,
) -> int:
    """Retract every un-dismissed stamphog approval posted at a head other than ``current_head_sha``.

    Keyed off ``posted_review_id`` alone — only the approve path ever sets it, and filtering on
    ``verdict=APPROVED`` too would miss a run that posted its approval but crashed (or lost a
    supersession race) before the verdict was saved, leaving that orphan standing forever.

    Returns the number dismissed. Idempotent via ``approval_dismissed_at``: a run already stamped is
    excluded, so a retry (or the activity re-running after the task skip already handled it) won't
    re-dismiss. Each dismissal is stamped right after its GitHub call so a mid-loop failure resumes
    cleanly on retry.
    """
    stale_runs = list(
        ReviewRun.objects.for_team(team_id)
        .filter(
            pull_request=pull_request,
            posted_review_id__isnull=False,
            approval_dismissed_at__isnull=True,
        )
        .exclude(head_sha=current_head_sha)
    )
    if not stale_runs:
        return 0

    client = StamphogGitHubClient(repo_config.installation_id)
    dismissed = 0
    for stale in stale_runs:
        if stale.posted_review_id is None:
            continue  # excluded by the query filter; narrows the Optional for the type checker
        client.dismiss_pr_review(repo_config.repository, pull_request.pr_number, stale.posted_review_id, message)
        stale.approval_dismissed_at = timezone.now()
        stale.save(update_fields=["approval_dismissed_at", "updated_at"])
        dismissed += 1
    return dismissed
