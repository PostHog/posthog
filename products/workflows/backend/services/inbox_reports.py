"""Workflows started by an Inbox report, and who may act on the report they carry."""

from uuid import UUID

from posthog.models import Team, User

from products.cdp.backend.internal_events import INBOX_REPORT_READY_EVENT
from products.signals.backend.facade.api import may_read_reports
from products.tasks.backend.facade.workflow_tasks import InboxReportClaimSkipReason
from products.workflows.backend.services.hog_flow_reads import get_workflow_ref


def subscribes_to_inbox_reports(filters: object) -> bool:
    events = filters.get("events") if isinstance(filters, dict) else None
    return isinstance(events, list) and any(
        isinstance(event, dict) and event.get("id") == INBOX_REPORT_READY_EVENT for event in events
    )


def inbox_report_claim_skip_reason(
    *, team: Team, workflow_id: UUID, owner_id: int
) -> InboxReportClaimSkipReason | None:
    """Why the workflow's task may not claim the report its run names, or None when it may.

    A report id in the run proves nothing: a captured product event can carry the same name, and a
    test run can carry any id. Only Signals emits on the internal-event trigger, and the task runs as
    the owner, who must still be able to read reports.
    """
    workflow = get_workflow_ref(team_id=team.id, workflow_id=workflow_id, user_access_control=None, required_level=None)
    if workflow.trigger_type != "internal-event" or not subscribes_to_inbox_reports(workflow.trigger_filters):
        return InboxReportClaimSkipReason.NOT_INBOX_TRIGGER
    owner = User.objects.filter(id=owner_id).first()
    if owner is None or not may_read_reports(user=owner, team=team):
        return InboxReportClaimSkipReason.NO_REPORT_ACCESS
    return None
