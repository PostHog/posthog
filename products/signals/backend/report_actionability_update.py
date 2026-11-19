from django.db import transaction

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ActionabilityAssessment, ActionabilityChoice
from products.signals.backend.models import SignalReport, SignalReportArtefact

INBOX_ACTIONABILITY_EXPLANATION = "Changed in the inbox."

# The pipeline sends a `not_actionable` report back to Potential. A person's `not_actionable` keeps the
# report in the inbox instead, because Dismiss and Snooze are the actions that take a report out of it.
_STATUS_FOR_ACTIONABILITY = {
    ActionabilityChoice.IMMEDIATELY_ACTIONABLE: SignalReport.Status.READY,
    ActionabilityChoice.REQUIRES_HUMAN_INPUT: SignalReport.Status.PENDING_INPUT,
    ActionabilityChoice.NOT_ACTIONABLE: SignalReport.Status.READY,
}

_MOVABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})


class ActionabilityRequired(Exception):
    """The report has no judgment to keep the actionability from, and the change names none."""


def update_report_actionability(
    *,
    report: SignalReport,
    actionability: ActionabilityChoice | None,
    already_addressed: bool | None,
    attribution: ArtefactAttribution,
) -> bool:
    """Append an attributed `actionability_judgment`, and return whether a value changed.

    A value left as None keeps the one in the latest judgment. Both values share one artefact, so a
    change to either one makes the person the setter of both, and the agent keeps both on later runs.

    A new actionability moves a Ready or Needs input report to the status in `_STATUS_FOR_ACTIONABILITY`.
    A report in any other status keeps it. A change never starts work by itself: an actionability
    judgment does not re-evaluate auto-start.
    """
    with transaction.atomic():
        locked = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        previous = SignalReportArtefact.latest_content(
            team_id=report.team_id, report_id=str(report.id), model=ActionabilityAssessment
        )
        new_actionability = actionability or (previous.actionability if previous else None)
        if new_actionability is None:
            raise ActionabilityRequired()
        if already_addressed is None:
            already_addressed = previous.already_addressed if previous else False
        if (
            previous is not None
            and previous.actionability == new_actionability
            and previous.already_addressed == already_addressed
        ):
            return False
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            attribution=attribution,
            content=ActionabilityAssessment(
                explanation=INBOX_ACTIONABILITY_EXPLANATION,
                actionability=new_actionability,
                already_addressed=already_addressed,
            ),
        )
        update_fields = ["updated_at"]
        target = _STATUS_FOR_ACTIONABILITY[new_actionability]
        actionability_changed = previous is None or previous.actionability != new_actionability
        if actionability_changed and locked.status in _MOVABLE_STATUSES and locked.status != target:
            update_fields = locked.transition_to(
                target, error=f"Requires human input: {INBOX_ACTIONABILITY_EXPLANATION}"
            )
            locked._transition_actor = attribution  # type: ignore[attr-defined]
        locked.save(update_fields=update_fields)
    return True
