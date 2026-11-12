"""The external issues a report is about, recorded as `source_issue` artefacts.

A GitHub issue reaches the inbox two ways: the GitHub source ingests it as a signal, or a scout
reads it and files a report itself. Only the first carried the issue's identity, so a scout's report
never commented on the issue, and the issue's own signal later grouped by embedding alone and often
opened a second report. A scout now names the issue when it files the report, and this module is the
one place that writes and reads that record:

- `append_source_issues` writes one row per new issue and, after commit, starts the GitHub
  writeback for a report that is visible in the inbox.
- `open_report_for_source_issue` is the exact match grouping tries before embedding similarity.
- `source_issues_by_report` is what the writeback and the report serializer read.
- `source_issue_author_reviewers` names the members who filed the issues, so the scout report tools
  can route the report to them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Sequence

from django.db import transaction

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_schemas import SourceIssue, SuggestedReviewerEntry
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportGithubComment,
    SignalTeamConfig,
)
from products.signals.backend.pr_owner_assignments import github_identity_source
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = logging.getLogger(__name__)

AUTHOR_LOOKUP_EGRESS_SOURCE = "signals_reviewers"

# A report in one of these states no longer takes new signals by exact issue match. A GitHub issue
# that comes back after its report closed falls through to embedding matching, as it did before.
CLOSED_REPORT_STATUSES = (
    SignalReport.Status.RESOLVED,
    SignalReport.Status.SUPPRESSED,
    SignalReport.Status.FAILED,
    SignalReport.Status.CLOSED,
    SignalReport.Status.DELETED,
)


def parse_source_issue_url(url: str) -> SourceIssue | None:
    """The normalized GitHub issue a URL names, or None when it names no GitHub issue."""
    ref = GitHubIntegrationBase.parse_issue_url(url.strip())
    if ref is None:
        return None
    return SourceIssue.github(ref.repository, ref.number)


def _url_filter(url: str) -> str:
    # The closing quote is part of the match, so `.../issues/12` never matches `.../issues/123`.
    return f'"url":{json.dumps(url)}'


def source_issues_by_report(*, team_id: int, report_ids: Collection[str]) -> dict[str, list[SourceIssue]]:
    """Each report's source issues, oldest first, in one query over the reports."""
    if not report_ids:
        return {}
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id__in=list(report_ids), type=SignalReportArtefact.ArtefactType.SOURCE_ISSUE
        )
        .order_by("created_at")
        .values_list("report_id", "content")
    )
    issues: dict[str, list[SourceIssue]] = {}
    for report_id, content in rows:
        issue = SourceIssue.model_validate_json(content)
        held = issues.setdefault(str(report_id), [])
        if issue not in held:
            held.append(issue)
    return issues


def append_source_issues(
    *, team_id: int, report_id: str, issues: Sequence[SourceIssue], attribution: ArtefactAttribution
) -> list[SourceIssue]:
    """Record the issues the report does not hold yet, returning the ones written.

    Additive and deduplicated, like typed report links: naming an issue twice is a no-op, so a
    retried edit writes nothing new and starts no second writeback. Must run inside the caller's
    report transaction. The writeback is scheduled on commit, so a rolled-back write never comments,
    and it only comments on a report that is visible in the inbox.
    """
    held = source_issues_by_report(team_id=team_id, report_ids=[report_id]).get(report_id, [])
    written: list[SourceIssue] = []
    for issue in issues:
        if issue in held or issue in written:
            continue
        SignalReportArtefact.add_log(team_id=team_id, report_id=report_id, content=issue, attribution=attribution)
        written.append(issue)
    if written:
        transaction.on_commit(lambda: schedule_source_issue_writeback(team_id=team_id, report_id=report_id))
    return written


def schedule_source_issue_writeback(*, team_id: int, report_id: str, signals: list[dict] | None = None) -> None:
    """Queue the GitHub writeback for a report that is visible in the inbox.

    Scout reports skip research, so the inbox notification workflow that comments for a researched
    report never runs for them. Grouping also calls this with the issue's signal when that signal
    joins the report, and the per-issue claim in the writeback keeps that from posting a second
    comment. The task re-checks the team opt-in and the report status itself.
    """
    from products.signals.backend.github_writeback import COMMENT_STATUSES  # noqa: PLC0415 - it imports this module

    if not SignalReport.objects.filter(team_id=team_id, id=report_id, status__in=COMMENT_STATUSES).exists():
        return
    _queue_writeback(team_id=team_id, report_id=report_id, signals=signals)


def schedule_writeback_for_status_change(*, team_id: int, report_id: str, status: str) -> None:
    """Queue the GitHub writeback after the report moved to `status`, for both researched and scout reports.

    A move to a visible status can post the first comment, and any status with a line edits a
    comment that went out already. A move to another status has nothing to write.
    """
    from products.signals.backend.github_writeback import COMMENT_STATUSES, STATUS_LINES  # noqa: PLC0415

    if status not in STATUS_LINES:
        return
    if not SignalTeamConfig.objects.filter(team_id=team_id, github_issue_writeback_enabled=True).exists():
        return
    if (
        status not in COMMENT_STATUSES
        and not SignalReportGithubComment.objects.for_team(team_id)
        .filter(report_id=report_id, commented_at__isnull=False)
        .exists()
    ):
        return
    _queue_writeback(team_id=team_id, report_id=report_id, signals=None)


def _queue_writeback(*, team_id: int, report_id: str, signals: list[dict] | None) -> None:
    from products.signals.backend.github_writeback_tasks import (  # noqa: PLC0415 - keep Celery off the import path
        post_source_issue_links,
    )

    post_source_issue_links.delay(team_id=team_id, report_id=report_id, signals=signals)


def open_report_for_source_issue(*, team_id: int, url: str) -> SignalReport | None:
    """The oldest open report that names this GitHub issue as its source, if any.

    Reads the team's `source_issue` rows through the (team, type) index, so the cost per signal is
    bounded by how many issues the team's reports name, not by its artefact log.
    """
    issue = parse_source_issue_url(url)
    if issue is None:
        return None
    report_ids = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.SOURCE_ISSUE,
            content__contains=_url_filter(issue.url),
        )
        .values_list("report_id", flat=True)
        .distinct()
    )
    return (
        SignalReport.objects.filter(team_id=team_id, id__in=list(report_ids))
        .exclude(status__in=CLOSED_REPORT_STATUSES)
        .order_by("created_at")
        .first()
    )


def _issue_author(
    team_id: int, issue: SourceIssue, integrations: dict[str, GitHubIntegration | None]
) -> tuple[str, int] | None:
    """The author's lowercased login and immutable GitHub user id, or None for a bot or an unreadable issue."""
    if issue.repository not in integrations:
        integrations[issue.repository] = GitHubIntegration.first_for_team_repository(
            team_id, issue.repository, source=AUTHOR_LOOKUP_EGRESS_SOURCE, priority=Priority.NORMAL
        )
    github = integrations[issue.repository]
    if github is None:
        return None
    response = github.api_request(
        "GET",
        f"/repos/{issue.repository}/issues/{issue.number}",
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}",
        retry_transient=False,
    )
    response.raise_for_status()
    payload = response.json()
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict) or user.get("type") == "Bot":
        return None
    login = user.get("login")
    github_id = user.get("id")
    if not isinstance(login, str) or not login.strip() or login.lower().endswith("[bot]"):
        return None
    if not isinstance(github_id, int) or isinstance(github_id, bool):
        return None
    return login.strip().lower(), github_id


def source_issue_author_reviewers(*, team_id: int, issues: Sequence[SourceIssue]) -> list[SuggestedReviewerEntry]:
    """The organization members who filed these GitHub issues, as reviewer entries in issue order.

    A member matches only when the GitHub account they linked has the author's user id as well as the
    login. Anyone can file an issue in a public repository, and a login a member gave up can be
    registered by someone else, so the login alone would route the report to the wrong person.

    Best effort: an issue no team installation can read, a failed or shed GitHub call, a bot author,
    and an author outside the team's organization each add no one, and none of them fails the
    report write. Costs one GitHub call per issue, so call it before the report transaction opens.
    """
    integrations: dict[str, GitHubIntegration | None] = {}
    authors: dict[str, tuple[int, SourceIssue]] = {}
    for issue in issues:
        try:
            author = _issue_author(team_id, issue, integrations)
        except Exception:
            logger.warning(
                "signals.source_issue_author_lookup_failed",
                extra={"team_id": team_id, "repository": issue.repository, "number": issue.number},
                exc_info=True,
            )
            continue
        if author is not None:
            login, github_id = author
            authors.setdefault(login, (github_id, issue))
    members = resolve_org_github_login_to_users(team_id, authors) if authors else {}
    entries: list[SuggestedReviewerEntry] = []
    for login, (github_id, issue) in authors.items():
        member = members.get(login)
        identity = github_identity_source(member, login) if member is not None else None
        if member is None or identity is None or identity[1] != github_id:
            continue
        entries.append(
            SuggestedReviewerEntry(
                github_login=login,
                user_uuid=str(member.uuid),
                reason=f"Filed the source issue {issue.repository}#{issue.number}.",
            )
        )
    return entries
