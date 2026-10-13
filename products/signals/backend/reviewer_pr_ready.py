"""Open a report's implementation pull request ready for review when a suggested reviewer asked for it.

Every self-driving pull request opens as a draft, and a draft only runs a narrowed CI matrix, so a
reviewer who wants to know whether the change is green has to mark it ready by hand and then wait
for the full matrix to start from scratch. Draft stays the default, because a ready pull request
runs the full matrix on every push and that is runner spend somebody has to choose. Opt-in through
`SignalUserAutonomyConfig.github_open_pull_request_ready` over
`SignalTeamConfig.default_open_pull_request_ready`, and best effort throughout: a GitHub failure
must never break the claim, sync, or webhook that triggered it.
"""

from __future__ import annotations

import json

from django.db import transaction

import structlog

from posthog.models import User
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    normalized_github_logins_from_reviewer_payloads,
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
)

logger = structlog.get_logger(__name__)

# A draft carrying this label is an explicit "do not spend runners on this", so marking it ready
# would override the clearer instruction. The label is a repository convention, so a repository that
# does not use it simply never matches.
SKIP_READY_LABELS = frozenset({"no-ci"})

# Only a pull request that could still be a draft is worth a GitHub call. UNKNOWN is included
# because a row that never recorded a state is far more often a live pull request than a closed one,
# and the task re-reads the real draft state from GitHub before it marks anything ready.
FLIPPABLE_PR_STATES = frozenset(
    {
        SignalReportAssignment.PrState.DRAFT,
        SignalReportAssignment.PrState.UNKNOWN,
    }
)


def schedule_open_pull_request_ready(
    *,
    team_id: int,
    report_id: str,
    pr_url: str | None,
    pr_state: str | None,
) -> None:
    """Queue the ready-for-review transition for a report's pull request, after the current commit.

    Only the paths where a pull request first reaches a report call this, so no later event re-queues
    it. The worker guards the rest: a pull request whose draft state a person has already moved is
    left alone, which is what holds even when this job sits in a backlog behind them.

    Enqueued on commit so nothing is marked ready if the write rolls back, and so the GitHub calls
    run on a worker instead of holding up a claim or a webhook. `robust=True` keeps a broker outage
    from failing a write that already committed.
    """
    if not pr_url or (pr_state or SignalReportAssignment.PrState.UNKNOWN) not in FLIPPABLE_PR_STATES:
        return

    # noqa: PLC0415 because `tasks` imports this module for the task body, so a module-level
    # import here would be a cycle.
    from products.signals.backend.tasks import open_implementation_pr_for_review  # noqa: PLC0415

    transaction.on_commit(
        lambda: open_implementation_pr_for_review.delay(
            team_id=team_id,
            report_id=str(report_id),
            pr_url=pr_url,
        ),
        robust=True,
    )


def _resolved_reviewer_users(*, team_id: int, report_id: str) -> list[User]:
    """The report's current suggested reviewers that resolve to a PostHog user in this team's org.

    Reads only the latest `suggested_reviewers` row, which is the live reviewer set, so a reviewer
    removed from the list no longer decides anything.
    """
    latest = (
        SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        )
        .order_by("-created_at")
        .first()
    )
    if latest is None:
        return []
    try:
        payloads = json.loads(latest.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(payloads, list):
        return []
    reviewer_rows = [row for row in payloads if isinstance(row, dict)]

    # A reviewer is a PostHog user, not a GitHub account: an org member who never connected GitHub is
    # stored by uuid with a null login, and reviewer identity gives the uuid precedence over a login
    # that could since have been reassigned. Resolving logins alone would drop the first group and
    # silently fall back to the team default for them.
    uuid_to_user = resolve_org_users_by_uuid(
        team_id, (str(row["user_uuid"]) for row in reviewer_rows if row.get("user_uuid"))
    )
    login_to_user = resolve_org_github_login_to_users(
        team_id,
        normalized_github_logins_from_reviewer_payloads(row for row in reviewer_rows if not row.get("user_uuid")),
    )

    # A union rather than a per-row walk: this answers one yes/no question over the whole reviewer
    # set, so reviewer order carries nothing, and taking the resolvers' own output avoids matching a
    # stored uuid against a live one by hand.
    return list({user.id: user for user in (*uuid_to_user.values(), *login_to_user.values())}.values())


def should_open_pull_request_ready(*, team_id: int, report_id: str) -> bool:
    """Whether this report's pull request should open ready for review rather than draft.

    Resolved per suggested reviewer, using their own setting and falling back to the team default,
    then unioned, since one reviewer wanting the full CI matrix is not in conflict with another
    reviewer's preference. A team that turned the default on gets it for reports whose reviewers
    resolve to no PostHog user either, because that setting means "our self-driving pull requests
    open ready".
    """
    team_default = bool(
        SignalTeamConfig.objects.filter(team_id=team_id)
        .values_list("default_open_pull_request_ready", flat=True)
        .first()
    )

    users = _resolved_reviewer_users(team_id=team_id, report_id=report_id)
    if not users:
        return team_default

    preferences = dict(
        SignalUserAutonomyConfig.objects.filter(user_id__in={user.id for user in users}).values_list(
            "user_id", "github_open_pull_request_ready"
        )
    )

    def resolved_for(user: User) -> bool:
        preference = preferences.get(user.id)
        return team_default if preference is None else preference

    return any(resolved_for(user) for user in users)


def open_pull_request_ready_for_review(*, team_id: int, report_id: str, pr_url: str) -> bool:
    """Take the report's pull request out of draft when its reviewers asked for that. Returns whether it moved.

    Returns False when there was nothing to do, which covers nobody opting in and a pull request
    that is already ready, closed, or labelled `no-ci`. A failed call also returns False, and this
    raises nothing.
    """
    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return False

    if not should_open_pull_request_ready(team_id=team_id, report_id=report_id):
        return False

    parsed = GitHubIntegration.parse_pull_request_url(pr_url)
    if parsed is None:
        return False

    try:
        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    except Exception:
        logger.exception(
            "signals.reviewer_pr_ready.integration_lookup_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
        )
        return False
    if github is None:
        return False

    try:
        result = github.mark_pull_request_ready_for_review(
            parsed.repository, parsed.number, skip_labels=SKIP_READY_LABELS
        )
    except Exception:
        logger.exception(
            "signals.reviewer_pr_ready.mark_ready_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
        )
        return False
    if not result.get("success"):
        logger.warning(
            "signals.reviewer_pr_ready.mark_ready_failed",
            team_id=team_id,
            report_id=report_id,
            repository=parsed.repository,
            pr_number=parsed.number,
            error=result.get("error"),
        )
        return False

    changed = bool(result.get("changed"))
    logger.info(
        "signals.reviewer_pr_ready.evaluated",
        team_id=team_id,
        report_id=report_id,
        repository=parsed.repository,
        pr_number=parsed.number,
        changed=changed,
        reason=result.get("reason"),
    )
    return changed
