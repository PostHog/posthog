"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import logging
from functools import partial
from typing import Literal

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.claim_display_name import claim_display_name
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
)
from products.signals.backend.report_assignments import ReportClaimConflict, claim_holder, claim_report
from products.signals.backend.report_claim_follow_up import record_report_claimed
from products.signals.backend.report_claims import get_active_claim, is_claim_of_person

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


@frozen
class SlackClaimOutcome:
    status: Literal["claimed", "already_yours", "claimed_by_other", "not_claimable", "not_found"]
    holder_name: str | None = None


def claim_report_from_slack(team_id: int, report_id: str, *, user_id: int) -> SlackClaimOutcome:
    """Claim a report for the PostHog user behind a Slack "I'm on it" click.

    The click never takes a claim over. A person who wants a report that someone else holds does that
    in PostHog, where they can see who holds it.
    """
    report = SignalReport.objects.filter(id=report_id, team_id=team_id).first()
    user = User.objects.filter(id=user_id).first()
    if report is None or user is None:
        return SlackClaimOutcome(status="not_found")

    held = get_active_claim(team_id=team_id, report_id=report.id)
    # claim_report treats a claim that the person's agent holds as another actor's claim.
    if held is not None and is_claim_of_person(held, user.id):
        return SlackClaimOutcome(status="already_yours")

    actor = ArtefactAttribution.from_user(user.id)
    try:
        claim_report(
            report=report,
            actor=actor,
            user=user,
            was_impersonated=False,
            on_new_claim=partial(
                record_report_claimed,
                team_id=team_id,
                report_id=str(report.id),
                actor=actor,
                scoped_team_ids=None,
                was_impersonated=False,
            ),
        )
    except ReportClaimConflict:
        held = get_active_claim(team_id=team_id, report_id=report.id)
        if held is None:
            return SlackClaimOutcome(status="not_claimable")
        return SlackClaimOutcome(status="claimed_by_other", holder_name=claim_display_name(report, claim_holder(held)))
    return SlackClaimOutcome(status="claimed")
