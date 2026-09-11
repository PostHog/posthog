"""Report state actions shared across entrypoints (API, Slack interactivity)."""

from __future__ import annotations

import logging

from django.db import transaction

from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import Dismissal, SafetyJudgment
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
)

logger = logging.getLogger(__name__)

# The statuses a report sits in when PostHog declined to implement it on its own: the safety judge
# rejected it (SUPPRESSED at birth, or FAILED carrying the judge's error), or the pipeline has not
# researched it yet (POTENTIAL, CANDIDATE). READY and PENDING_INPUT need no override because they
# already offer Create PR, and RESOLVED, IN_PROGRESS and DELETED hold no decision to overrule.
SAFETY_OVERRIDE_STATUSES = frozenset(
    {
        SignalReport.Status.POTENTIAL,
        SignalReport.Status.CANDIDATE,
        SignalReport.Status.FAILED,
        SignalReport.Status.SUPPRESSED,
    }
)


class SafetyOverrideNotAllowed(Exception):
    """The report's status holds no decision a person can overrule."""


@frozen
class SafetyOverride:
    """What an override changed. The caller's analytics event reads from this."""

    previous_status: str
    judge_explanation: str | None


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
    # The linked implementation PR is closed by the post_save receiver on suppression or snooze
    # (see receivers.close_pr_when_report_dismissed) — no per-caller call needed here.
    return True


def latest_safety_explanation(team_id: int, report_id: str) -> str | None:
    """The safety judge's reason for rejecting this report, from its latest `safety_judgment`.

    None when the report holds no verdict, the latest verdict is safe, or the verdict left no
    explanation — in each case there is no judge's reason to quote. An unreadable verdict is None
    too: this answers "what can we quote back to a person", not "is this report safe". The gate that
    asks the second question is `receivers._is_safety_suppressed`, and it fails the other way.
    """
    content = (
        SignalReportArtefact.objects.filter(
            report_id=report_id, team_id=team_id, type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT
        )
        .order_by("-created_at")
        .values_list("content", flat=True)
        .first()
    )
    if not content:
        return None
    try:
        verdict = SafetyJudgment.model_validate_json(content)
    except ValidationError:
        return None
    if verdict.choice or not verdict.explanation or not verdict.explanation.strip():
        return None
    return verdict.explanation.strip()


def override_safety_judgment(*, report: SignalReport, user_id: int, note: str | None = None) -> SafetyOverride:
    """Record that a person decided to implement a report PostHog would not implement on its own.

    Two writes, in one transaction, both of which must land before the implementation task exists:

    - A `safety_judgment` artefact with `choice: true`, naming the person and their steer. The
      newest row of a status type is the report's canonical one, so this makes the human call the
      report's safety status: its text can be indexed again on the next judged write (see
      `receivers._is_safety_suppressed`), and the work log keeps an audit row a reviewer can read.
    - A move to READY, which is the status a merged pull request resolves from (see
      `report_assignments._apply_pr_report_state`). Without it the PR merges and leaves the report
      sitting where the judge left it.

    This grants a caller nothing it could not already do: creating an implementation task from a
    report has never checked the report's status or its safety verdict. What it adds is the record
    of who made the call, and a report whose lifecycle can now finish.

    Raises `SafetyOverrideNotAllowed` when the report's status holds no such decision to overrule.
    """
    with transaction.atomic():
        # Row-locked: two people pressing Create PR on the same blocked report must not both
        # transition it, and the status read below is what decides whether this call is allowed.
        locked = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        if locked.status not in SAFETY_OVERRIDE_STATUSES:
            raise SafetyOverrideNotAllowed(
                f"Reports with status '{locked.status}' hold no safety judgment to override."
            )
        previous_status = locked.status
        judge_explanation = latest_safety_explanation(locked.team_id, str(locked.id))

        updated_fields = locked.transition_to(SignalReport.Status.READY, human_override=True)
        locked.save(update_fields=updated_fields)

        explanation = f"Overridden by user {user_id}, who implemented this report from status '{previous_status}'."
        if judge_explanation:
            explanation += f" The safety judge had said: {judge_explanation}"
        trimmed_note = (note or "").strip()
        if trimmed_note:
            explanation += f" Their instructions for the run: {trimmed_note}"
        SignalReportArtefact.append_status(
            team_id=locked.team_id,
            report_id=str(locked.id),
            content=SafetyJudgment(choice=True, explanation=explanation),
            attribution=ArtefactAttribution.from_user(user_id),
        )

    # Refresh the caller's instance so the response it serializes shows the report's new status.
    report.refresh_from_db()
    return SafetyOverride(previous_status=previous_status, judge_explanation=judge_explanation)
