"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import logging

from django.db import transaction

from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.implementation_pr import close_implementation_pr_for_report
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
)

logger = logging.getLogger(__name__)


def suppress_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> bool:
    """Suppress (dismiss) a report from a Slack 'Dismiss' click. Idempotent — an
    already-suppressed report is treated as success; returns False if the report
    doesn't exist or the transition isn't allowed.

    `user_id` is the PostHog user the clicking Slack identity resolved to — the caller already
    resolves it to gate the dismiss to org members. When present the dismissal is attributed to
    them; the `slack_user_id` is kept in the content either way as the Slack-side trace.
    """
    # Row-lock the report so concurrent Dismiss clicks can't both transition + write artefacts.
    with transaction.atomic():
        report = SignalReport.objects.filter(id=report_id, team_id=team_id).select_for_update().first()
        if report is None:
            logger.warning(
                "suppress_report_from_slack: report not found", extra={"report_id": report_id, "team_id": team_id}
            )
            return False

        if report.status == SignalReport.Status.SUPPRESSED:
            return True

        try:
            updated_fields = report.transition_to(SignalReport.Status.SUPPRESSED)
        except InvalidStatusTransition:
            logger.warning(
                "suppress_report_from_slack: invalid transition",
                extra={"report_id": report_id, "team_id": team_id, "status": report.status},
            )
            return False

        report.save(update_fields=updated_fields)
        # Attribute to the resolved PostHog user when the caller mapped the Slack click to one;
        # fall back to system if not. Either way the slack_user_id stays in the content as the
        # Slack-side trace.
        attribution = ArtefactAttribution.from_user(user_id) if user_id is not None else ArtefactAttribution.system()
        SignalReportArtefact.append_dismissal(
            team_id=team_id,
            report_id=str(report.id),
            content=Dismissal(reason="slack_dismiss", slack_user_id=slack_user_id),
            attribution=attribution,
        )

    # Comment on and close the linked implementation PR only after the suppression commits — a
    # dismissed report means the fix isn't wanted. Deferred past the atomic block because it's an
    # irreversible external side effect; kept best-effort so a GitHub failure never undoes the dismiss.
    close_implementation_pr_for_report(team_id, str(report_id))
    return True
