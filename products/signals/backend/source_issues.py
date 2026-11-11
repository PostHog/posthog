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
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence

from django.db import transaction

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalReportGithubComment,
    SignalTeamConfig,
)

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
