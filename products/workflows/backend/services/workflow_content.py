from typing import Any, Optional
from uuid import UUID

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal
from products.workflows.backend.services.workflow_secrets import strip_content_secrets

# The content of a workflow: everything the draft cycle stages and publish promotes, and nothing
# else. Metadata (name, description) and lifecycle (status) always apply to the live row. The draft
# blob is a full snapshot of these fields so publish is a plain copy, not a merge.
DRAFT_CONTENT_FIELDS = (
    "actions",
    "edges",
    "trigger",
    "trigger_masking",
    "conversion",
    "exit_condition",
    "email_sending_rate_limit",
    "abort_action",
    "variables",
)


def snapshot_flow_content(flow: HogFlow) -> dict:
    return snapshot_content_fields({field: getattr(flow, field) for field in DRAFT_CONTENT_FIELDS})


def snapshot_content_fields(snapshot: dict[str, Any]) -> dict:
    # The model's legacy default for actions/edges is `{}`, but the API shape is a list — normalize
    # so re-validation of a snapshot (draft publish, revision restore) doesn't choke on a
    # never-edited column.
    for field in ("actions", "edges"):
        if not snapshot[field]:
            snapshot[field] = []
    # Defensively strip secrets: a legacy row written before encryption shipped still has plaintext
    # secret inputs in `actions`, and this snapshot feeds revision content — which must never carry
    # secrets. New rows are already stripped, so this is a no-op for them.
    return strip_content_secrets(snapshot)


def trigger_has_audience(trigger: Optional[dict]) -> bool:
    """Whether a dispatch of this workflow fans out to persons matched by the trigger's filters.

    Only the batch trigger does. A schedule trigger fires one person-less run, so there is no
    audience to preview and no blast-radius token to demand.
    """
    return (trigger or {}).get("type") == "batch"


def unstage_workflow_proposals(*, team_id: int, hog_flow_id: UUID) -> None:
    """Put every approved suggestion back in the queue, because the draft it was approved into is
    about to be replaced.

    Approved means one thing here: this suggestion is what sits in the draft. Discarding the draft,
    restoring a revision, approving a different suggestion or editing over it all replace that
    draft, and publish reads approved as "this is what shipped", so it must not record one against
    a version that never carried it. A suggestion whose change survives the replacement comes back
    to the queue too, which costs a person one more approval rather than a wrong history entry.
    """
    WorkflowProposal.objects.filter(
        team_id=team_id, hog_flow_id=hog_flow_id, status=WorkflowProposal.Status.APPROVED
    ).update(status=WorkflowProposal.Status.SUGGESTED, resolved_at=None, resolved_by=None)
