"""Returns a ready report's findings to the support ticket that raised it.

Support tickets flow into the inbox as signals, get researched against the codebase, and the result
lands in the inbox only. The teammate answering the customer never sees it, so they reply from what
they knew before the research ran. This posts the findings back onto the ticket as a private note for
them to draw on, which closes the loop without putting agent output in front of a customer.
"""

from __future__ import annotations

from urllib.parse import quote

import structlog

from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.conversations.backend.facade import api as conversations_facade
from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.report_urls import ReportLinkSource, build_report_url

logger = structlog.get_logger(__name__)


def task_can_write_support_ticket_update(*, team_id: int, report_id: str, task_id: str, pr_url: str) -> bool:
    from products.tasks.backend.facade import api as tasks_facade

    return SignalReportTask.objects.filter(
        team_id=team_id,
        report_id=report_id,
        task_id=task_id,
        relationship="implementation",
    ).exists() and tasks_facade.is_verified_task_pr_url(task_id=task_id, team_id=team_id, pr_url=pr_url)


def _note_body(report_url: str) -> str:
    """A pointer, deliberately carrying none of the report's own content.

    Comments authorize as the `comment` resource while reports authorize as `task`, so a teammate with
    ticket access but no inbox access can read this note. Copying the title or summary here would hand
    them research they aren't entitled to; a link makes them pass the report's own access check. The
    ticket's Associated reports panel reads through that check, so the findings still surface in the
    ticket for anyone allowed to see them.
    """
    return (
        f"**Self-driving investigated this ticket.** Internal note, not sent to the customer.\n\nReport: {report_url}"
    )


def _ticket_ids(signals: list[dict]) -> list[str]:
    return sorted(
        {
            str(signal.get("source_id") or "")
            for signal in signals
            if signal.get("source_product") == SignalSourceProduct.CONVERSATIONS and signal.get("source_id")
        }
    )


def _post_notes(team: Team, report_id: str, ticket_ids: list[str], body: str, dedupe_key: str, kind: str) -> int:
    posted = 0
    for ticket_id in ticket_ids:
        try:
            comment_id = conversations_facade.post_ticket_internal_note(
                team_id=team.pk,
                ticket_id=ticket_id,
                content=body,
                dedupe_key=dedupe_key,
            )
        except Exception:
            logger.exception(
                "Failed to post signals note to support ticket",
                report_id=report_id,
                ticket_id=ticket_id,
                team_id=team.pk,
                kind=kind,
            )
            continue
        if comment_id is not None:
            posted += 1
    logger.info(
        "Posted signals notes to support tickets",
        report_id=report_id,
        team_id=team.pk,
        tickets=len(ticket_ids),
        posted=posted,
        kind=kind,
    )
    return posted


def post_report_findings_to_tickets(team: Team, report_id: str, signals: list[dict]) -> int:
    """Post a ready report's findings as a private note on each support ticket that contributed to it.

    Returns the number of notes posted. Best-effort: a failure here must not fail the report's
    notification flow, so per-ticket errors are logged rather than raised.
    """
    ticket_ids = _ticket_ids(signals)
    if not ticket_ids:
        return 0

    if not SignalReport.objects.filter(id=report_id, team_id=team.pk).exists():
        return 0

    body = _note_body(build_report_url(team.pk, report_id, ReportLinkSource.SUPPORT))

    return _post_notes(team, report_id, ticket_ids, body, f"signals_report:{report_id}", "report")


def post_pull_request_to_tickets(team: Team, report_id: str, pr_url: str, signals: list[dict]) -> int:
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None:
        return 0
    pr_url = f"https://github.com/{quote(parsed.owner, safe='')}/{quote(parsed.repo, safe='')}/pull/{parsed.number}"
    ticket_ids = _ticket_ids(signals)
    if not ticket_ids or not SignalReport.objects.filter(id=report_id, team_id=team.pk).exists():
        return 0

    body = (
        "[PostHog bot] **Self-driving linked a pull request to this report.** Internal note, not sent to the customer.\n\n"
        f"Pull request: {pr_url}\n"
        f"Report: {build_report_url(team.pk, report_id, ReportLinkSource.SUPPORT)}"
    )
    public_body = f"[PostHog bot] Self-driving opened a pull request related to this ticket: {pr_url}"
    posted = 0
    first_error: Exception | None = None
    for ticket_id in ticket_ids:
        try:
            comment_id = conversations_facade.post_ticket_automated_update(
                team_id=team.pk,
                ticket_id=ticket_id,
                public_content=public_body,
                private_content=body,
                dedupe_key=f"signals_pr:{report_id}:{pr_url}",
            )
        except Exception as exc:
            logger.exception(
                "Failed to post signals pull request to support ticket",
                report_id=report_id,
                ticket_id=ticket_id,
                team_id=team.pk,
            )
            if first_error is None:
                first_error = exc
            continue
        if comment_id is not None:
            posted += 1
    if first_error is not None:
        raise first_error
    logger.info(
        "Posted signals pull request to support tickets",
        report_id=report_id,
        team_id=team.pk,
        tickets=len(ticket_ids),
        posted=posted,
    )
    return posted
