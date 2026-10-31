"""Approving a suggested change: stage the workflow's draft from the suggestion under the row lock."""

from collections.abc import Callable
from datetime import datetime
from typing import Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.workflows.backend.facade.contracts import (
    ProposalApproval,
    WorkflowDraftChanged,
    WorkflowDraftExists,
    WorkflowProposalConflicts,
    WorkflowProposalNotFound,
    WorkflowProposalResolved,
)
from products.workflows.backend.facade.enums import WorkflowProposalStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_content import snapshot_flow_content
from products.workflows.backend.services.hog_flow_writes import field_values
from products.workflows.backend.services.workflow_proposals import (
    get_proposal,
    lock_proposal,
    merge_proposal_content,
    resolve_proposal,
    staged_proposal_changes,
    unstage_workflow_proposals,
)


def approve_proposal(
    *,
    team_id: int,
    workflow_team_id: int,
    hog_flow_id: UUID,
    proposal_id: UUID,
    overwrite: bool,
    expected_draft_updated_at: Optional[datetime],
    resolved_by_id: Optional[int],
    check_runnable: Callable[[dict], None],
) -> ProposalApproval:
    """Stage the suggestion into the workflow's draft and mark it approved. Approval only stages, like a
    revision restore: publish still previews and confirms. `team_id` scopes the suggestion and
    `workflow_team_id` the workflow row. `check_runnable` receives the merged content and raises when
    the graph could not run."""
    with transaction.atomic():
        # The row lock serializes concurrent approvals; the second sees what the first wrote.
        locked = HogFlow.objects.select_for_update().get(pk=hog_flow_id, team_id=workflow_team_id)
        proposal = get_proposal(team_id=team_id, hog_flow_id=locked.id, proposal_id=proposal_id)
        if proposal is None:
            raise WorkflowProposalNotFound()
        locked_proposal = lock_proposal(team_id=team_id, proposal_id=proposal.id)
        if locked_proposal.status != WorkflowProposalStatus.SUGGESTED:
            raise WorkflowProposalResolved()
        if locked.draft and not overwrite:
            raise WorkflowDraftExists()
        staged = staged_proposal_changes(team_id=locked.team_id, hog_flow_id=locked.pk, proposal_id=locked_proposal.id)
        if staged.conflicts:
            raise WorkflowProposalConflicts(staged.conflicts)
        if (
            locked.draft
            and expected_draft_updated_at is not None
            and locked.draft_updated_at != expected_draft_updated_at
        ):
            raise WorkflowDraftChanged()
        previous = field_values(locked)
        # The draft is a full snapshot (live plus what the suggestion changes), so publish stays
        # a plain copy. A field the suggestion merely echoed is not staged, since writing it back
        # would undo a later edit the conflict check let through.
        merged = merge_proposal_content(snapshot_flow_content(locked), staged.changes)
        # Create validated the merge against the graph as it was then; it can have moved since.
        check_runnable(merged)
        locked.draft = merged
        locked.draft_updated_at = timezone.now()
        # Proposal content carries no secrets, so the draft re-attaches them from live on publish.
        locked.draft_encrypted_inputs = None
        locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

        # The new draft replaces what was staged; an earlier approval stays only if the draft still carries it.
        unstage_workflow_proposals(team_id=locked.team_id, hog_flow_id=locked.pk)

        locked_proposal = resolve_proposal(
            team_id=team_id,
            proposal_id=locked_proposal.id,
            status=WorkflowProposalStatus.APPROVED,
            resolved_by_id=resolved_by_id,
        )
    return ProposalApproval(proposal=locked_proposal, previous=previous, current=field_values(locked))
