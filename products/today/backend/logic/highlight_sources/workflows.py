from products.workflows.backend.facade.api import get_email_sending_state, list_owned_workflow_health
from products.workflows.backend.facade.contracts import OwnedWorkflowHealth

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact, short
from ..highlight_types import Candidate, Context, Found, Source

SENDING_SUSPENDED = "Email sending is suspended for this project"
SENDING_SUSPENDED_DETAIL = "Workflow and broadcast emails are not delivered. Contact support to turn sending back on"
EMAILS_PAUSED = "Emails are paused for workflow ‘{workflow}’"
EMAILS_PAUSED_DETAIL = "It sends no emails until sending resumes"
FAILING = "Workflow ‘{workflow}’ failed {failed} times in the last 7 days"
FAILING_DETAIL = "{share:.0%} of its runs failed"
SUGGESTIONS = "{count} suggested changes to workflow ‘{workflow}’ are waiting for review"
SUGGESTION = "1 suggested change to workflow ‘{workflow}’ is waiting for review"
SUGGESTIONS_DETAIL = "Approve or reject them on the Self-driving tab"
SUGGESTION_DETAIL = "Approve or reject it on the Self-driving tab"
MIN_FAILED = 10
MIN_FAILED_SHARE = 0.1


def find(context: Context) -> Found:
    workflows = list_owned_workflow_health(team=context.team, user=context.user, limit=20)
    if not workflows:
        return Found()
    candidates = [candidate for workflow in workflows for candidate in _candidates(workflow)]
    state = get_email_sending_state(context.team.id)
    if state is not None and state.suspended_at is not None:
        candidates.insert(0, _sending_suspended())
    return Found(items=tuple(candidates))


def _sending_suspended() -> Candidate:
    # Suspension stops every email step in the project, so it outranks any one workflow's problem.
    return Candidate(
        key="workflows:email-sending-suspended",
        label=HighlightLabel.RISK,
        family="workflows",
        importance=0.95,
        relevance=1.0,
        title=SENDING_SUSPENDED,
        detail=SENDING_SUSPENDED_DETAIL,
        url="/workflows/reputation",
    )


def _candidates(workflow: OwnedWorkflowHealth) -> list[Candidate]:
    name = short(workflow.name)
    candidates = []
    if workflow.email_sending_paused:
        candidates.append(
            _candidate(
                workflow,
                "emails-paused",
                HighlightLabel.RISK,
                importance=0.85,
                title=EMAILS_PAUSED.format(workflow=name),
                detail=EMAILS_PAUSED_DETAIL,
                tab="workflow",
            )
        )
    runs = workflow.succeeded + workflow.failed
    if workflow.failed >= MIN_FAILED and workflow.failed >= MIN_FAILED_SHARE * runs:
        share = workflow.failed / runs
        candidates.append(
            _candidate(
                workflow,
                "failing",
                HighlightLabel.RISK,
                importance=min(1.0, 0.5 + share / 2),
                title=FAILING.format(workflow=name, failed=exact(workflow.failed)),
                detail=FAILING_DETAIL.format(share=share),
                tab="invocations",
            )
        )
    if workflow.pending_suggestions:
        one = workflow.pending_suggestions == 1
        candidates.append(
            _candidate(
                workflow,
                "suggestions",
                HighlightLabel.OPPORTUNITY,
                importance=0.4,
                title=(SUGGESTION if one else SUGGESTIONS).format(
                    workflow=name, count=exact(workflow.pending_suggestions)
                ),
                detail=SUGGESTION_DETAIL if one else SUGGESTIONS_DETAIL,
                tab="self-driving",
            )
        )
    return candidates


def _candidate(
    workflow: OwnedWorkflowHealth,
    kind: str,
    label: HighlightLabel,
    *,
    importance: float,
    title: str,
    detail: str,
    tab: str,
) -> Candidate:
    return Candidate(
        key=f"workflow:{workflow.workflow_id}:{kind}",
        label=label,
        family="workflows",
        importance=importance,
        relevance=1.0,
        title=title,
        detail=detail,
        url=f"/workflows/{workflow.workflow_id}/{tab}",
    )


SOURCE = Source(name="workflows", find=find, scopes=("hog_flow:read",))
