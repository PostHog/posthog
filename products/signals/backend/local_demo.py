import json
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction
from django.utils import timezone

from posthog.local_demo import require_local_development
from posthog.models import OrganizationMembership, Team, User

from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportArtefact
from products.signals.backend.suggested_reviewer_index import sync_suggested_reviewer_index


def seed_local_demo_reports(*, team_id: int, user_id: int) -> list[str]:
    """Insert personal Inbox examples without the report pipeline's dispatch/save hooks.

    These fixtures exercise ready, pending-input, reviewer and claimed-work rendering.
    Stable bulk inserts keep a developer's subsequent triage decisions on repeat runs.
    """
    require_local_development()
    team = Team.objects.get(id=team_id)
    if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=user_id).exists():
        raise ValueError("The selected user must belong to the project's organization")
    user = User.objects.get(id=user_id)
    now = timezone.now()
    report_ids: list[str] = []
    for status in (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT):
        waiting = status == SignalReport.Status.PENDING_INPUT
        report_id = uuid5(NAMESPACE_URL, f"posthog:local-inbox-demo:v1:{team_id}:{user_id}:{status}")
        actionability = "requires_human_input" if waiting else "immediately_actionable"
        title = "Demo: choose the signup success metric" if waiting else "Demo: clarify the signup form error"
        summary = (
            "The demo signup flow needs a success metric. Should success mean submitting the form "
            "or reaching the confirmation screen? Choose one before implementing the change."
            if waiting
            else "The demo signup form shows a generic error when the email field is empty. "
            "Add a specific message beside the field so the next step is clear."
        )
        with transaction.atomic():
            SignalReport.objects.bulk_create(
                [
                    SignalReport(
                        id=report_id,
                        team_id=team_id,
                        status=status,
                        title=title,
                        summary=summary,
                        signal_count=2,
                        total_weight=2,
                        signals_at_run=5,
                        signals_researched=2,
                        first_visible_at=now,
                        latest_actionability=actionability,
                        latest_already_addressed=False,
                        tags=["local-demo", "signup"],
                    )
                ],
                ignore_conflicts=True,
            )
            report = SignalReport.objects.get(id=report_id, team_id=team_id)
            contents: dict[str, object] = {
                "priority_judgment": {"priority": "P2", "explanation": "A small improvement to the demo signup flow."},
                "actionability_judgment": {
                    "actionability": actionability,
                    "already_addressed": False,
                    "explanation": summary,
                },
                "suggested_reviewers": [{"user_uuid": str(user.uuid), "reason": "Owner of this local demo."}],
                "note": {
                    "note": "Synthetic example for local development.",
                    "author": "local demo",
                },
            }
            if not waiting:
                contents["work_claim"] = {"display_name": user.first_name or "Demo user"}
            SignalReportArtefact.objects.bulk_create(
                [
                    SignalReportArtefact(
                        id=uuid5(report_id, kind),
                        team_id=team_id,
                        report=report,
                        type=kind,
                        content=json.dumps(content),
                        actor_kind=SignalActorKind.USER if kind == "work_claim" else None,
                        created_by_id=user_id if kind == "work_claim" else None,
                    )
                    for kind, content in contents.items()
                ],
                ignore_conflicts=True,
            )
            sync_suggested_reviewer_index(team_id=team_id, report_id=str(report_id))
        report_ids.append(str(report_id))
    return report_ids
