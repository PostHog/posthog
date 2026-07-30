"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import json
import logging
from typing import Literal

from django.db import transaction

from posthog.models.user import User

from products.signals.backend.artefact_schemas import Dismissal, SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
)

logger = logging.getLogger(__name__)


def suppress_report_from_slack(
    team_id: int,
    report_id: str,
    *,
    slack_user_id: str | None = None,
    user_id: int | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> bool:
    """Suppress (dismiss) a report from a Slack 'Dismiss' click. Idempotent — an
    already-suppressed report is treated as success; returns False if the report
    doesn't exist or the transition isn't allowed.

    `user_id` is the PostHog user the clicking Slack identity resolved to — the caller already
    resolves it to gate the dismiss to org members. When present the dismissal is attributed to
    them; the `slack_user_id` is kept in the content either way as the Slack-side trace.

    `reason` is the code chosen in the dismiss modal (falls back to "slack_dismiss" when the
    click carried none) and `note` is the optional free-form text from the same modal.
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
            content=Dismissal(reason=reason or "slack_dismiss", note=note, slack_user_id=slack_user_id),
            attribution=attribution,
        )
    # The linked implementation PR is closed by the post_save receiver on suppression or snooze
    # (see receivers.close_pr_when_report_dismissed) — no per-caller call needed here.
    return True


RemoveReviewerOutcome = Literal["removed", "not_a_reviewer", "not_found"]


def remove_reviewer_from_slack(team_id: int, report_id: str, *, user_id: int) -> RemoveReviewerOutcome:
    """Drop `user_id` from a report's suggested reviewers, triggered by the Slack 'Not me' button.

    Appends a new `suggested_reviewers` status (latest-wins) with the user's GitHub login removed,
    attributed to them. Row-locks the report so concurrent 'Not me' clicks can't clobber each
    other's removals. Returns "not_a_reviewer" when the user isn't a listed reviewer (no linked
    GitHub login, or a login that isn't on the report), and "not_found" when the report is gone.
    """
    # Prefetch the GitHub identity relations get_github_login() reads, so resolving the login is one
    # query rather than a lookup per relation.
    from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415 — keeps repo-activity deps off the module import path
        _github_identity_prefetches,
    )

    user = User.objects.filter(id=user_id).prefetch_related(*_github_identity_prefetches()).first()
    login = user.get_github_login() if user is not None else None
    login_lc = login.lower() if login else None

    with transaction.atomic():
        report = SignalReport.objects.filter(id=report_id, team_id=team_id).select_for_update().first()
        if report is None:
            return "not_found"

        artefact = (
            report.artefacts.filter(type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
            .order_by("-created_at")
            .first()
        )
        if artefact is None or login_lc is None:
            return "not_a_reviewer"

        try:
            entries = json.loads(artefact.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            return "not_a_reviewer"
        if not isinstance(entries, list):
            return "not_a_reviewer"

        remaining = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and str(entry.get("github_login", "")).strip().lower() == login_lc)
        ]
        if len(remaining) == len(entries):
            return "not_a_reviewer"

        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report.id),
            content=SuggestedReviewers([SuggestedReviewerEntry.model_validate(entry) for entry in remaining]),
            attribution=ArtefactAttribution.from_user(user_id),
        )
    return "removed"
