"""Label a report's implementation pull request, so GitHub can tell it apart from other bot work.

A self-driving pull request opens under the shared bot identity every other piece of automation
pushes under, and its `posthog-self-driving/` head branch is not something GitHub search can match
on. So a team that wants a saved search, a notification rule, or an exclusion has nothing to build
one from. One label solves all three at once.

Opt-in through `SignalTeamConfig.pull_request_label_enabled`, because the label lands on a
repository the team shares with everybody. Best effort throughout: a GitHub failure must never
break the pull request link or the report write that triggered it.
"""

from __future__ import annotations

from django.db import transaction

import structlog

from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport, SignalReportAssignment, SignalTeamConfig

logger = structlog.get_logger(__name__)

# What a team gets when it turns the label on without naming one. Reads the same way in a GitHub
# search as it does in the inbox settings, so nobody has to translate between the two.
DEFAULT_PULL_REQUEST_LABEL = "self-driving"

# Only a live pull request is worth a GitHub call. UNKNOWN is included because a row that never
# recorded a state is far more often open than closed.
LABELLABLE_PR_STATES = frozenset(
    {
        SignalReportAssignment.PrState.OPEN,
        SignalReportAssignment.PrState.DRAFT,
        SignalReportAssignment.PrState.UNKNOWN,
    }
)


def schedule_pull_request_label(
    *,
    team_id: int,
    report_id: str,
    pr_url: str | None,
    pr_state: str | None,
) -> None:
    """Queue the label for a report's pull request, after the current transaction commits.

    Enqueued on commit so nothing is labelled if the write rolls back, and so the GitHub calls run
    on a worker instead of holding up the claim, sync, or webhook that queued it. `robust=True`
    keeps a broker outage from failing a write that already committed.
    """
    if not pr_url or (pr_state or SignalReportAssignment.PrState.UNKNOWN) not in LABELLABLE_PR_STATES:
        return

    # noqa: PLC0415 because `tasks` imports this module for the task body, so a module-level
    # import here would be a cycle.
    from products.signals.backend.tasks import label_implementation_pr  # noqa: PLC0415

    transaction.on_commit(
        lambda: label_implementation_pr.delay(
            team_id=team_id,
            report_id=str(report_id),
            pr_url=pr_url,
        ),
        robust=True,
    )


def configured_pull_request_label(team_id: int) -> str | None:
    """The label this team wants on its self-driving pull requests, or None when it wants none."""
    config = (
        SignalTeamConfig.objects.filter(team_id=team_id)
        .values("pull_request_label_enabled", "pull_request_label")
        .first()
    )
    if config is None or not config["pull_request_label_enabled"]:
        return None
    return (config["pull_request_label"] or "").strip() or DEFAULT_PULL_REQUEST_LABEL


def apply_pull_request_label(*, team_id: int, report_id: str, pr_url: str) -> str | None:
    """Put the team's label on the report's pull request. Returns the label GitHub applied.

    Returns None when there was nothing to do, which covers a team that never turned the label on
    and a repository with no GitHub integration. A failed call also returns None, and this raises
    nothing.
    """
    # The team's setting first: a team that never turned the label on is the common case, so it
    # answers in one query rather than two.
    label = configured_pull_request_label(team_id)
    if label is None:
        return None

    if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
        return None

    parsed = GitHubIntegration.parse_pull_request_url(pr_url)
    if parsed is None:
        return None

    log = logger.bind(team_id=team_id, report_id=report_id, repository=parsed.repository, pr_number=parsed.number)
    try:
        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
    except Exception:
        log.exception("signals.pull_request_label.integration_lookup_failed")
        return None
    if github is None:
        return None

    try:
        result = github.add_pull_request_labels(parsed.repository, parsed.number, [label])
    except Exception:
        log.exception("signals.pull_request_label.label_failed")
        return None
    if not result.get("success"):
        log.warning("signals.pull_request_label.label_failed", error=result.get("error"))
        return None

    if label not in (result.get("labels") or []):
        log.warning("signals.pull_request_label.label_not_applied")
        return None
    log.info("signals.pull_request_label.labelled")
    return label
