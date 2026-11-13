"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import logging

from django.db import transaction

from products.signals.backend.artefact_schemas import Dismissal
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

        # Attribute to the resolved PostHog user when the caller mapped the Slack click to one;
        # fall back to system if not. The receivers name this actor in the GitHub comments and in
        # the status-change label. Either way the slack_user_id stays in the content as the
        # Slack-side trace.
        attribution = ArtefactAttribution.from_user(user_id) if user_id is not None else ArtefactAttribution.system()
        report._transition_actor = attribution  # type: ignore[attr-defined]
        report.save(update_fields=updated_fields)
        SignalReportArtefact.append_dismissal(
            team_id=team_id,
            report_id=str(report.id),
            content=Dismissal(state="suppressed", reason="slack_dismiss", slack_user_id=slack_user_id),
            attribution=attribution,
        )
    # The linked implementation PR is closed by the post_save receiver on suppression or snooze
    # (see receivers.close_pr_when_report_dismissed) — no per-caller call needed here.
    return True


def resolve_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> bool:
    """Resolve a report from a Slack 'Mark resolved' click. Idempotent — an already-resolved
    report is treated as success; returns False if the report doesn't exist or the transition
    isn't allowed.

    Like a resolve through the state API, it says the work is done without the inbox pull request,
    so that pull request is superseded and the receiver closes it.
    """
    with transaction.atomic():
        report = SignalReport.objects.filter(id=report_id, team_id=team_id).select_for_update().first()
        if report is None:
            logger.warning(
                "resolve_report_from_slack: report not found", extra={"report_id": report_id, "team_id": team_id}
            )
            return False

        if report.status == SignalReport.Status.RESOLVED:
            return True

        try:
            updated_fields = report.transition_to(SignalReport.Status.RESOLVED)
        except InvalidStatusTransition:
            logger.warning(
                "resolve_report_from_slack: invalid transition",
                extra={"report_id": report_id, "team_id": team_id, "status": report.status},
            )
            return False

        attribution = ArtefactAttribution.from_user(user_id) if user_id is not None else ArtefactAttribution.system()
        report._transition_actor = attribution  # type: ignore[attr-defined]
        report._close_pr_on_resolve = True  # type: ignore[attr-defined]
        report._wrote_dismissal_feedback = True  # type: ignore[attr-defined]
        report.save(update_fields=updated_fields)
        SignalReportArtefact.append_dismissal(
            team_id=team_id,
            report_id=str(report.id),
            content=Dismissal(state="resolved", reason="slack_resolve", slack_user_id=slack_user_id),
            attribution=attribution,
        )
    return True
