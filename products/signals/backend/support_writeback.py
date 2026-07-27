"""Returns a ready report's findings to the support ticket that raised it.

Support tickets flow into the inbox as signals, get researched against the codebase, and the result
lands in the inbox only. The teammate answering the customer never sees it, so they reply from what
they knew before the research ran. This posts the findings back onto the ticket as a private note for
them to draw on, which closes the loop without putting agent output in front of a customer.
"""

from __future__ import annotations

from django.conf import settings

import structlog

from posthog.models import Team

from products.conversations.backend.facade import api as conversations_facade
from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.models import SignalReport

logger = structlog.get_logger(__name__)


def _note_body(report_url: str) -> str:
    """A pointer, deliberately carrying none of the report's own content.

    Comments authorize as the `comment` resource while reports authorize as `task`, so a teammate with
    ticket access but no inbox access can read this note. Copying the title or summary here would hand
    them research they aren't entitled to; a link makes them pass the report's own access check. The
    ticket's Associated reports panel reads through that check, so the findings still surface in the
    ticket for anyone allowed to see them.
    """
    return (
        f"**Self-driving investigated this ticket.** Internal note, not sent to the customer.\n\nFindings: {report_url}"
    )


def post_report_findings_to_tickets(team: Team, report_id: str, signals: list[dict]) -> int:
    """Post a ready report's findings as a private note on each support ticket that contributed to it.

    Returns the number of notes posted. Best-effort: a failure here must not fail the report's
    notification flow, so per-ticket errors are logged rather than raised.
    """
    ticket_ids = sorted(
        {
            str(signal.get("source_id") or "")
            for signal in signals
            if signal.get("source_product") == SignalSourceProduct.CONVERSATIONS and signal.get("source_id")
        }
    )
    if not ticket_ids:
        return 0

    if not SignalReport.objects.filter(id=report_id, team_id=team.pk).exists():
        return 0

    body = _note_body(f"{settings.SITE_URL}/project/{team.pk}/inbox/{report_id}")

    posted = 0
    for ticket_id in ticket_ids:
        try:
            comment_id = conversations_facade.post_ticket_internal_note(
                team_id=team.pk,
                ticket_id=ticket_id,
                content=body,
                dedupe_key=f"signals_report:{report_id}",
            )
        except Exception:
            logger.exception(
                "Failed to post signals findings to support ticket",
                report_id=report_id,
                ticket_id=ticket_id,
                team_id=team.pk,
            )
            continue
        if comment_id is not None:
            posted += 1
    logger.info(
        "Posted signals findings to support tickets",
        report_id=report_id,
        team_id=team.pk,
        tickets=len(ticket_ids),
        posted=posted,
    )
    return posted
