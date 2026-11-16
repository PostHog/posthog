"""The external issues a report is about, recorded as `source_issue` artefacts.

A GitHub issue reaches the inbox two ways: the GitHub source ingests it as a signal, or a scout
reads it and files a report itself. Only the first carried the issue's identity, so a scout's report
never commented on the issue, and the issue's own signal later grouped by embedding alone and often
opened a second report. A scout now names the issue when it files the report, and this module is the
one place that writes and reads that record:

- `append_source_issues` writes one row per new issue and, after commit, starts the GitHub
  writeback for a READY report.
- `open_report_for_source_issue` is the exact match grouping tries before embedding similarity.
- `source_issues_by_report` is what the writeback and the report serializer read.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence

from django.db import transaction

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact

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
    and it only comments on a READY report.
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
    """Queue the GitHub writeback for a READY report's source issues.

    Scout reports skip research, so the inbox notification workflow that comments for a researched
    report never runs for them. A source issue only gets a comment once the GitHub source ingested
    it, which often happens after the scout filed the report, so grouping calls this again with the
    issue's signal when that signal joins the report. The task re-checks the team opt-in and the
    report status itself.
    """
    if not SignalReport.objects.filter(team_id=team_id, id=report_id, status=SignalReport.Status.READY).exists():
        return
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
