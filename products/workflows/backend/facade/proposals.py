"""Suggested changes to a workflow, the per-workflow opt-in that allows them, and what each change did."""

from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE
from products.workflows.backend.services.proposal_approval import approve_proposal
from products.workflows.backend.services.workflow_proposals import (
    PROPOSAL_MERGE_BY_ID_FIELDS,
    as_the_serializer_stores_it,
    count_proposals,
    create_proposal,
    get_proposal,
    get_proposal_by_source_id,
    is_optimization_enabled,
    list_proposals,
    lock_proposal,
    merge_proposal_content,
    proposal_conflicts,
    proposal_outcome,
    resolve_proposal,
    set_optimization_enabled,
    staged_proposal_changes,
    target_metric_in,
    unstage_workflow_proposals,
    version_outcome,
)

__all__ = [
    "approve_proposal",
    "HOG_FLOW_VERSION_APP_SOURCE",
    "PROPOSAL_MERGE_BY_ID_FIELDS",
    "as_the_serializer_stores_it",
    "count_proposals",
    "create_proposal",
    "get_proposal",
    "get_proposal_by_source_id",
    "is_optimization_enabled",
    "list_proposals",
    "lock_proposal",
    "merge_proposal_content",
    "proposal_conflicts",
    "proposal_outcome",
    "resolve_proposal",
    "set_optimization_enabled",
    "staged_proposal_changes",
    "target_metric_in",
    "unstage_workflow_proposals",
    "version_outcome",
]
