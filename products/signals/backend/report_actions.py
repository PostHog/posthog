"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import json
import logging

from django.db import transaction

from products.signals.backend.models import InvalidStatusTransition, SignalReport, SignalReportArtefact

logger = logging.getLogger(__name__)


def suppress_report_from_slack(team_id: int, report_id: str, *, slack_user_id: str | None = None) -> bool:
    """Suppress (dismiss) a report from a Slack 'Dismiss' click. Idempotent — an
    already-suppressed report is treated as success; returns False if the report
    doesn't exist or the transition isn't allowed.
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
        SignalReportArtefact.objects.create(
            team_id=team_id,
            report=report,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
            content=json.dumps({"reason": "slack_dismiss", "note": None, "slack_user_id": slack_user_id}),
        )
    return True
