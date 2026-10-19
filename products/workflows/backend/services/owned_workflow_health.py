from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import OwnedWorkflowHealth
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal

HEALTH_WINDOW = timedelta(days=7)


def list_owned_workflow_health(*, team: Team, user: User, limit: int) -> list[OwnedWorkflowHealth]:
    """The person's newest live workflows, built in workflows itself, with runs and pending suggestions."""
    flows = list(
        HogFlow.objects.filter(
            team_id=team.id, created_by_id=user.id, status=HogFlow.State.ACTIVE, origin_product__isnull=True
        )
        .order_by("-updated_at")
        .values("id", "name", "email_sending_paused_at")[:limit]
    )
    if not flows:
        return []
    flow_ids = [flow["id"] for flow in flows]
    pending = dict(
        WorkflowProposal.objects.for_team(team.id)
        .filter(hog_flow_id__in=flow_ids, status__in=WorkflowProposal.OPEN_STATUSES)
        .order_by()
        .values("hog_flow_id")
        .annotate(count=Count("id"))
        .values_list("hog_flow_id", "count")
    )
    # The workflows facade loads during django.setup(), and app_metrics2 pulls in posthog.schema.
    from posthog.api import app_metrics2  # noqa: PLC0415 — keeps the heavy dep off the import path

    runs = app_metrics2.fetch_app_metric_totals_by_source(
        team_id=team.id, app_source="hog_flow", after=timezone.now() - HEALTH_WINDOW
    )
    return [
        OwnedWorkflowHealth(
            workflow_id=flow["id"],
            name=flow["name"] or "",
            succeeded=runs.get(str(flow["id"]), {}).get("succeeded", 0),
            failed=runs.get(str(flow["id"]), {}).get("failed", 0),
            email_sending_paused=flow["email_sending_paused_at"] is not None,
            pending_suggestions=pending.get(flow["id"], 0),
        )
        for flow in flows
    ]
