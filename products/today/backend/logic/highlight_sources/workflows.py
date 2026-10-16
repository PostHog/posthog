from products.workflows.backend.facade.api import list_owned_workflow_health
from products.workflows.backend.facade.contracts import OwnedWorkflowHealth

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact, short
from ..highlight_types import Candidate, Context, Found, Source

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
    return Found(items=tuple(candidate for workflow in workflows for candidate in _candidates(workflow)))


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
