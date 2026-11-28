"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import logging
from typing import Literal

from django.db import transaction

from posthog.models.user import User

from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
)

logger = logging.getLogger(__name__)

SlackStateOutcome = Literal["changed", "unchanged", "refused"]

# The statuses a report resolves from directly. A report in monitoring has open checks to cancel, and an
# archived one must not reach resolved through the archive, so both go through the inbox instead.
_SLACK_RESOLVABLE_STATUSES = frozenset(
    {
        SignalReport.Status.READY,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.FAILED,
        SignalReport.Status.CLOSED,
    }
)


def _slack_dismissal(
    state: Literal["resolved", "suppressed"], reason: str, *, slack_user_id: str | None, user_id: int | None
) -> Dismissal:
    # Readers of the dismissal content join on the PostHog user, which a Slack id alone can't reach.
    user_uuid = User.objects.filter(id=user_id).values_list("uuid", flat=True).first() if user_id is not None else None
    return Dismissal(
        state=state,
        reason=reason,
        slack_user_id=slack_user_id,
        user_id=user_id,
        user_uuid=str(user_uuid) if user_uuid else None,
    )


def suppress_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> SlackStateOutcome:
    """Suppress (dismiss) a report from a Slack 'Dismiss' click. Idempotent — an
    already-suppressed report returns "unchanged", so a repeat click credits nobody; returns
    "refused" if the report doesn't exist or the transition isn't allowed.

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
            return "refused"

        if report.status == SignalReport.Status.SUPPRESSED:
            return "unchanged"

        try:
            updated_fields = report.transition_to(SignalReport.Status.SUPPRESSED)
        except InvalidStatusTransition:
            logger.warning(
                "suppress_report_from_slack: invalid transition",
                extra={"report_id": report_id, "team_id": team_id, "status": report.status},
            )
            return "refused"

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
            content=_slack_dismissal("suppressed", "slack_dismiss", slack_user_id=slack_user_id, user_id=user_id),
            attribution=attribution,
        )
    # The linked implementation PR is closed by the post_save receiver on suppression or snooze
    # (see receivers.close_pr_when_report_dismissed) — no per-caller call needed here.
    return "changed"


def resolve_report_from_slack(
    team_id: int, report_id: str, *, slack_user_id: str | None = None, user_id: int | None = None
) -> SlackStateOutcome:
    """Resolve a report from a Slack 'Mark resolved' click. Idempotent — an already-resolved
    report returns "unchanged", so a repeat click credits nobody; returns "refused" if the report
    doesn't exist or the transition isn't allowed, which includes every status outside
    `_SLACK_RESOLVABLE_STATUSES`.

    Like a resolve through the state API, it says the work is done without the inbox pull request,
    so that pull request is superseded and the receiver closes it.
    """
    with transaction.atomic():
        report = SignalReport.objects.filter(id=report_id, team_id=team_id).select_for_update().first()
        if report is None:
            logger.warning(
                "resolve_report_from_slack: report not found", extra={"report_id": report_id, "team_id": team_id}
            )
            return "refused"

        if report.status == SignalReport.Status.RESOLVED:
            return "unchanged"

        if report.status not in _SLACK_RESOLVABLE_STATUSES:
            logger.warning(
                "resolve_report_from_slack: status not resolvable from Slack",
                extra={"report_id": report_id, "team_id": team_id, "status": report.status},
            )
            return "refused"

        try:
            updated_fields = report.transition_to(SignalReport.Status.RESOLVED)
        except InvalidStatusTransition:
            logger.warning(
                "resolve_report_from_slack: invalid transition",
                extra={"report_id": report_id, "team_id": team_id, "status": report.status},
            )
            return "refused"

        attribution = ArtefactAttribution.from_user(user_id) if user_id is not None else ArtefactAttribution.system()
        report._transition_actor = attribution  # type: ignore[attr-defined]
        report._close_pr_on_resolve = True  # type: ignore[attr-defined]
        report._wrote_dismissal_feedback = True  # type: ignore[attr-defined]
        report.save(update_fields=updated_fields)
        SignalReportArtefact.append_dismissal(
            team_id=team_id,
            report_id=str(report.id),
            content=_slack_dismissal("resolved", "slack_resolve", slack_user_id=slack_user_id, user_id=user_id),
            attribution=attribution,
        )
    return "changed"
