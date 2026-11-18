"""Tells a GitHub issue that raised a report that self-driving has looked at it.

A GitHub issue flows into the inbox as a signal, gets researched against the codebase, and the
result lands in the inbox only. Nobody watching the issue hears anything, so a maintainer or an
outside contributor can start on work we already research. This comments a link to the report back
on the issue, which closes that loop. Opt-in per team, because the comment is public on the issue
thread.

A scout that files a report about an issue records it as a `source_issue` artefact instead of a
signal, so the writeback reads both (see `source_issues.py`). A scout usually files its report before
the team's GitHub source ingests the issue, so a source issue gets its comment when the report is
filed, without waiting for that signal. A report can name any issue URL, so a source issue gets a
comment only when the team's GitHub source syncs issues from its repository. Integration coverage
alone is not enough, because an organization-wide GitHub App installation can reach repositories
the team never connected. The rest of the path still applies: the team opted in, one of the team's
own GitHub integrations covers the repository, GitHub says the issue is open and unlocked, and each
(report, issue) pair gets one comment at most.

The comment carries one line for the report's status. The first comment goes out when the report
becomes visible in the inbox, and a later status change edits that comment instead of posting again.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from django.utils import timezone

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase, PullRequestRef
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalReport, SignalReportGithubComment, SignalTeamConfig
from products.signals.backend.report_urls import ReportLinkSource, build_report_url
from products.signals.backend.source_issues import source_issues_by_report
from products.warehouse_sources.backend.facade import api as warehouse_sources

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "signals_github_writeback"
CLAIM_LEASE = timedelta(minutes=10)
MAX_COMMENT_PAGES = 10


# The statuses the inbox lists a report in. Only these post a first comment on an issue.
COMMENT_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT, SignalReport.Status.FAILED})

_NO_FURTHER_WORK = "No further self-driving work is planned on this."
# A status without a line here leaves a posted comment as it is. A report that goes back to research
# keeps its last line until the research gives it a new status.
STATUS_LINES: dict[str, str] = {
    SignalReport.Status.PENDING_INPUT: "The team needs to make a decision before work starts.",
    SignalReport.Status.READY: "Research is done.",
    SignalReport.Status.FAILED: "Research stopped before it was complete.",
    SignalReport.Status.RESOLVED: _NO_FURTHER_WORK,
    SignalReport.Status.CLOSED: _NO_FURTHER_WORK,
    SignalReport.Status.SUPPRESSED: _NO_FURTHER_WORK,
    SignalReport.Status.DELETED: _NO_FURTHER_WORK,
}


def _comment_body(report_url: str, status_line: str, marker: str) -> str:
    """A pointer, deliberately carrying none of the report's own content.

    The comment is public on the issue thread, while the report is behind the PostHog project's own
    access check. Copying the title or the summary here would publish research that only the project
    is entitled to, so the comment says the work exists, which state it is in, and links to it.
    """
    return (
        f"PostHog self-driving picked up this issue. Status: {status_line}\n\n"
        "Somebody may already be working on it, so ask before you start a fix.\n\n"
        f"Report (team access only): {report_url}\n\n{marker}"
    )


def _issue_refs(signals: list[dict], source_issues: Sequence[SourceIssue] = ()) -> list[PullRequestRef]:
    """The open GitHub issues among a report's signals and its recorded source issues, each one once.

    A closed issue is answered already, and a locked one refuses comments, so neither is worth a
    call. A source issue carries no state of its own, so `_post_to_issue` reads it from GitHub
    before it comments.
    """
    refs: dict[tuple[str, int], PullRequestRef] = {}
    for signal in signals:
        if (
            signal.get("source_product") != SignalSourceProduct.GITHUB
            or signal.get("source_type") != SignalSourceType.ISSUE
        ):
            continue
        extra = signal.get("extra") or {}
        if extra.get("locked") or str(extra.get("state") or "").lower() != "open":
            continue
        ref = GitHubIntegrationBase.parse_issue_url(str(extra.get("html_url") or ""))
        if ref is not None:
            refs.setdefault((ref.repository.lower(), ref.number), ref)
    for issue in source_issues:
        owner, repo = issue.repository.split("/", 1)
        refs.setdefault((issue.repository, issue.number), PullRequestRef(owner=owner, repo=repo, number=issue.number))
    return list(refs.values())


def _find_comment(github: GitHubIntegration, repository: str, number: int, marker: str) -> dict | bool | None:
    """The issue comment that carries the marker, False when the issue has none, or None when the
    read is incomplete. An incomplete read cannot prove that a previous POST failed."""
    for page in range(1, MAX_COMMENT_PAGES + 1):
        response = github.api_request(
            "GET",
            f"/repos/{repository}/issues/{number}/comments",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100, "page": page},
            retry_transient=False,
        )
        response.raise_for_status()
        comments = response.json()
        if not isinstance(comments, list):
            return None
        for comment in comments:
            if isinstance(comment, dict) and marker in str(comment.get("body") or ""):
                return comment
        if len(comments) < 100:
            return False
    return None


def _post_to_issue(
    *,
    team_id: int,
    report_id: str,
    ref: PullRequestRef,
    body: str,
    marker: str,
    integrations: dict[str, GitHubIntegration | None],
) -> bool:
    """Comment on one issue, once per (report, issue). Returns whether a comment went out.

    Pending claims survive uncertain POST outcomes. After the lease expires, a later settle checks
    for the stable comment marker before it retries. The lease exceeds the activity timeout.

    ``integrations`` memoizes the integration per repository for one run, because resolving one
    costs an authenticated GitHub call per integration the team has.
    """
    # GitHub compares a repository path without case, while the unique constraint below does not,
    # so the raw spelling would let a case-only rename claim a second row and comment twice.
    repository = ref.repository.lower()

    # for_team scopes the lookup; get_or_create still needs team_id in the defaults, because a
    # queryset filter does not propagate into the row it creates.
    claim, created = SignalReportGithubComment.objects.for_team(team_id).get_or_create(
        report_id=report_id,
        repository=repository,
        number=ref.number,
        defaults={"team_id": team_id},
    )
    if claim.commented_at is not None:
        return False

    claims = SignalReportGithubComment.objects.for_team(team_id).filter(pk=claim.pk, commented_at__isnull=True)
    if not created:
        acquired_at = timezone.now()
        if not claims.filter(updated_at__lt=acquired_at - CLAIM_LEASE).update(updated_at=acquired_at):
            return False
        claim.updated_at = acquired_at
    owned_claim = claims.filter(updated_at=claim.updated_at)

    try:
        if repository not in integrations:
            # Background comments must leave the interactive GitHub budget available.
            integrations[repository] = GitHubIntegration.first_for_team_repository(
                team_id, repository, source=EGRESS_SOURCE, priority=Priority.BATCH
            )
        github = integrations[repository]
        if github is None:
            return False
        if not created:
            existing = _find_comment(github, repository, ref.number, marker)
            if existing is not False:
                if existing is not None:
                    owned_claim.update(commented_at=timezone.now())
                return False

        response = github.api_request(
            "GET",
            f"/repos/{repository}/issues/{ref.number}",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}",
            retry_transient=False,
        )
        response.raise_for_status()
        issue = response.json()
        if (
            not isinstance(issue, dict)
            or issue.get("state") != "open"
            or issue.get("locked") is not False
            or "pull_request" in issue
        ):
            return False
        if not owned_claim.filter(updated_at__gt=timezone.now() - CLAIM_LEASE).exists():
            return False
        outcome = github.comment_on_issue(repository, ref.number, body)
    except Exception:
        logger.exception(
            "signals.github_writeback_failed",
            report_id=report_id,
            team_id=team_id,
            repository=repository,
            number=ref.number,
        )
        return False

    if not outcome.get("success"):
        logger.warning(
            "signals.github_writeback_failed",
            report_id=report_id,
            team_id=team_id,
            repository=repository,
            number=ref.number,
            error=outcome.get("error"),
        )
        return False

    owned_claim.update(commented_at=timezone.now())
    return True


def _update_comment(
    *,
    team_id: int,
    report_id: str,
    claim: SignalReportGithubComment,
    body: str,
    marker: str,
    integrations: dict[str, GitHubIntegration | None],
) -> bool:
    """Edit the comment posted for this (report, issue) to the current body. Returns whether it changed.

    The row keeps no comment id, so the marker finds the comment. Concurrent runs write the same
    body, so no claim is necessary here.
    """
    repository = claim.repository
    try:
        if repository not in integrations:
            integrations[repository] = GitHubIntegration.first_for_team_repository(
                team_id, repository, source=EGRESS_SOURCE, priority=Priority.BATCH
            )
        github = integrations[repository]
        if github is None:
            return False
        comment = _find_comment(github, repository, claim.number, marker)
        if not isinstance(comment, dict) or comment.get("body") == body or comment.get("id") is None:
            return False
        response = github.api_request(
            "PATCH",
            f"/repos/{repository}/issues/comments/{comment['id']}",
            endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json_body={"body": body},
            retry_transient=False,
        )
        response.raise_for_status()
    except Exception:
        logger.exception(
            "signals.github_writeback_update_failed",
            report_id=report_id,
            team_id=team_id,
            repository=repository,
            number=claim.number,
        )
        return False
    return True


def post_report_link_to_github_issues(team: Team, report_id: str, signals: list[dict]) -> int:
    """Bring the report's comments on GitHub issues up to date with its status.

    A comment that went out already gets the current status line. A report that is visible in the
    inbox also comments a link on each GitHub issue that contributed to it, or that the report names
    as a `source_issue`, when that issue has no comment yet.

    Returns the number of comments posted. Best-effort: a failure here must not fail the report's
    notification flow, so per-issue errors are logged rather than raised.
    """
    if not SignalTeamConfig.objects.filter(team_id=team.pk, github_issue_writeback_enabled=True).exists():
        return 0

    status = SignalReport.objects.filter(id=report_id, team_id=team.pk).values_list("status", flat=True).first()
    status_line = STATUS_LINES.get(status) if status is not None else None
    if status_line is None:
        return 0

    marker = f"<!-- posthog:signal-report:{report_id} -->"
    body = _comment_body(build_report_url(team.pk, report_id, ReportLinkSource.GITHUB_COMMENT), status_line, marker)
    integrations: dict[str, GitHubIntegration | None] = {}
    updated = sum(
        _update_comment(
            team_id=team.pk, report_id=report_id, claim=claim, body=body, marker=marker, integrations=integrations
        )
        for claim in SignalReportGithubComment.objects.for_team(team.pk).filter(
            report_id=report_id, commented_at__isnull=False
        )
    )
    if updated:
        logger.info("signals.github_writeback_updated", report_id=report_id, team_id=team.pk, updated=updated)

    if status not in COMMENT_STATUSES:
        return 0

    source_issues = source_issues_by_report(team_id=team.pk, report_ids=[report_id]).get(report_id, [])
    if source_issues:
        synced = warehouse_sources.github_repositories_syncing(team.pk, "issues")
        source_issues = [issue for issue in source_issues if issue.repository in synced]
    refs = _issue_refs(signals, source_issues)
    if not refs:
        return 0

    posted = sum(
        _post_to_issue(
            team_id=team.pk, report_id=report_id, ref=ref, body=body, marker=marker, integrations=integrations
        )
        for ref in refs
    )
    logger.info(
        "signals.github_writeback_posted",
        report_id=report_id,
        team_id=team.pk,
        issues=len(refs),
        posted=posted,
    )
    return posted
