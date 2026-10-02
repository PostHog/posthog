from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.api.app_metrics2 import fetch_app_metric_totals

from products.workflows.backend.facade.contracts import (
    CreatedWorkflowProposal,
    LiveWorkflowContent,
    ProposalMetric,
    ProposalVersionOutcome,
    WorkflowProposalRecord,
)
from products.workflows.backend.facade.enums import WorkflowProposalStatus
from products.workflows.backend.metrics import (
    GUARDRAIL_LABELS,
    GUARDRAIL_METRICS,
    HOG_FLOW_VERSION_APP_SOURCE,
    MIN_EVIDENCE_SAMPLE,
    TARGET_CLICK_METRIC,
    TARGET_OPEN_METRIC,
    TARGET_SEND_METRIC,
    TARGET_UNTRACKED_METRIC,
)
from products.workflows.backend.models.hog_flow_optimization import HogFlowOptimization
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.models.workflow_proposal import WorkflowProposal

# Fields a proposal replaces wholesale. `actions` merges per step instead, since steps carry stable
# ids; edges have no id, and a variable list is short enough to carry whole.
PROPOSAL_WHOLE_LIST_FIELDS = ("edges", "variables")

PROPOSAL_MERGE_BY_ID_FIELDS = ("actions",)


def _to_record(proposal: WorkflowProposal) -> WorkflowProposalRecord:
    return WorkflowProposalRecord(
        id=proposal.id,
        title=proposal.title,
        rationale=proposal.rationale,
        content=proposal.content,
        evidence=proposal.evidence,
        step_id=proposal.step_id,
        base_version=proposal.base_version,
        status=WorkflowProposalStatus(proposal.status),
        source_id=proposal.source_id,
        created_at=proposal.created_at,
        resolved_at=proposal.resolved_at,
        resolved_by=proposal.resolved_by,
        applied_version=proposal.applied_version,
    )


def _proposals(hog_flow_id: UUID, status: str | None) -> QuerySet[WorkflowProposal]:
    # Applied ones order by the version that shipped them; the rest read as a queue, newest first.
    applied_only = status == WorkflowProposal.Status.APPLIED
    ordering = ("-applied_version", "-created_at") if applied_only else ("-created_at",)
    queryset = WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id).order_by(*ordering)
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def count_proposals(*, hog_flow_id: UUID, status: str | None) -> int:
    return _proposals(hog_flow_id, status).count()


def list_proposals(*, hog_flow_id: UUID, status: str | None, offset: int, limit: int) -> list[WorkflowProposalRecord]:
    queryset = _proposals(hog_flow_id, status).select_related("resolved_by")
    return [_to_record(proposal) for proposal in queryset[offset : offset + limit]]


def get_proposal(*, team_id: int, hog_flow_id: UUID, proposal_id: UUID) -> WorkflowProposalRecord | None:
    proposal = (
        WorkflowProposal.objects.select_related("resolved_by")
        .filter(team_id=team_id, hog_flow_id=hog_flow_id, id=proposal_id)
        .first()
    )
    return _to_record(proposal) if proposal is not None else None


def get_proposal_by_source_id(*, hog_flow_id: UUID, source_id: str) -> WorkflowProposalRecord | None:
    proposal = WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id, source_id=source_id).first()
    return _to_record(proposal) if proposal is not None else None


def create_proposal(
    *,
    hog_flow_id: UUID,
    title: str,
    rationale: str,
    content: dict[str, Any],
    evidence: dict[str, Any],
    step_id: str | None,
    base_version: int,
    source_id: str | None,
) -> CreatedWorkflowProposal:
    proposal = WorkflowProposal(
        hog_flow_id=hog_flow_id,
        title=title,
        rationale=rationale,
        content=content,
        evidence=evidence,
        step_id=step_id,
        base_version=base_version,
        source_id=source_id,
    )
    try:
        with transaction.atomic():
            proposal.save()
    except IntegrityError:
        # A concurrent create with the same source_id landed between the read and this save.
        existing = (
            WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id, source_id=source_id).first() if source_id else None
        )
        if existing is None:
            raise
        return CreatedWorkflowProposal(proposal=_to_record(existing), created=False)
    return CreatedWorkflowProposal(proposal=_to_record(proposal), created=True)


def lock_proposal(*, team_id: int, proposal_id: UUID) -> WorkflowProposalRecord:
    """Lock the proposal row until the caller's transaction ends."""
    return _to_record(WorkflowProposal.objects.select_for_update().get(team_id=team_id, id=proposal_id))


def resolve_proposal(
    *, team_id: int, proposal_id: UUID, status: WorkflowProposalStatus, resolved_by_id: int | None
) -> WorkflowProposalRecord:
    proposal = WorkflowProposal.objects.get(team_id=team_id, id=proposal_id)
    proposal.status = status
    proposal.resolved_at = timezone.now()
    proposal.resolved_by_id = resolved_by_id
    proposal.save(update_fields=["status", "resolved_at", "resolved_by"])
    return _to_record(proposal)


def unstage_workflow_proposals(hog_flow_id: UUID) -> None:
    """Put every approved suggestion back in the queue, because the draft it was approved into is
    about to be replaced.

    Approved means one thing here: this suggestion is what sits in the draft. Discarding the draft,
    restoring a revision, approving a different suggestion or editing over it all replace that
    draft, and publish reads approved as "this is what shipped", so it must not record one against
    a version that never carried it. A suggestion whose change survives the replacement comes back
    to the queue too, which costs a person one more approval rather than a wrong history entry.
    """
    WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id, status=WorkflowProposal.Status.APPROVED).update(
        status=WorkflowProposal.Status.SUGGESTED, resolved_at=None, resolved_by=None
    )


def version_outcome(
    *, team_id: int, hog_flow_id: UUID, version: int | None, after: datetime, step_id: str | None = None
) -> ProposalVersionOutcome | None:
    if version is None:
        return None
    # Scoped to the step the suggestion names; several email steps would otherwise share one denominator.
    totals = fetch_app_metric_totals(
        team_id=team_id,
        app_source=HOG_FLOW_VERSION_APP_SOURCE,
        app_source_id=f"{hog_flow_id}/{version}",
        breakdown_by="name",
        after=after,
        instance_id=step_id or None,
        name=[
            TARGET_SEND_METRIC,
            TARGET_OPEN_METRIC,
            TARGET_CLICK_METRIC,
            TARGET_UNTRACKED_METRIC,
            *GUARDRAIL_METRICS,
        ],
    ).totals
    sends = int(totals.get(TARGET_SEND_METRIC, 0))
    # Untracked sends can never record an open, so opens read against tracked sends; guardrails keep every send.
    tracked_sends = max(0, sends - int(totals.get(TARGET_UNTRACKED_METRIC, 0)))

    def rate(count: int, label: str, denominator: int) -> ProposalMetric:
        return {
            "metric": label,
            "value": (count / denominator) if denominator else None,
            "n": denominator,
            "below_minimum_sample": denominator < MIN_EVIDENCE_SAMPLE,
        }

    return {
        "version": version,
        "target": rate(int(totals.get(TARGET_OPEN_METRIC, 0)), "email open rate", tracked_sends),
        # Same denominator as opens: a send with tracking off can record neither.
        "click_through": rate(int(totals.get(TARGET_CLICK_METRIC, 0)), "click rate", tracked_sends),
        "guardrails": [rate(int(totals.get(name, 0)), GUARDRAIL_LABELS[name], sends) for name in GUARDRAIL_METRICS],
    }


def is_optimization_enabled(hog_flow_id: UUID) -> bool:
    return HogFlowOptimization.objects.filter(hog_flow_id=hog_flow_id, enabled=True).exists()


def set_optimization_enabled(*, hog_flow_id: UUID, enabled: bool) -> bool:
    """Turn suggestions on or off for one workflow. Returns whether the setting changed."""
    row = HogFlowOptimization.objects.filter(hog_flow_id=hog_flow_id).first()
    if row is None:
        # Turning it off for a workflow nobody turned on is a no-op, not a row saying "no".
        if not enabled:
            return False
        # get_or_create rather than create: two first-time enables race, and the loser of
        # the one-to-one constraint would answer 500 for a workflow that is now on.
        # nosemgrep: idor-lookup-without-team - team scope is enforced by TeamScopedManager
        row, created = HogFlowOptimization.objects.get_or_create(hog_flow_id=hog_flow_id, defaults={"enabled": True})
        if not created and not row.enabled:
            row.enabled = True
            row.save(update_fields=["enabled"])
            return True
        return created
    # Off keeps the row: how many tried this and stopped is a rollout question.
    if row.enabled == enabled:
        return False
    row.enabled = enabled
    row.save(update_fields=["enabled"])
    return True


def _item_id(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else None


def describe_steps(hog_flow: LiveWorkflowContent, step_ids: list[str]) -> list[str]:
    """Step names for a person to read. A step deleted since has no name left, so it keeps its id."""
    names = {_item_id(item): item.get("name") for item in hog_flow.content.get("actions") or []}
    return [names.get(step_id) or step_id for step_id in step_ids]


def conflicting_parts(
    hog_flow: LiveWorkflowContent, proposal: WorkflowProposalRecord, content: Optional[dict] = None
) -> list[str]:
    """Parts of the workflow the proposal changes that someone else already changed since it was
    written: step ids for `actions`, field names for everything else.

    The check follows merge semantics. A step merges per field, so only the fields the proposal sets
    on the steps it names are compared, as they were at `base_version` against as they are now. A
    whole-list field replaces the list, so any publish since counts. Every other field replaces one
    value, so that value is compared. An edit elsewhere merges cleanly, and an edit that already made
    the proposed change is nothing to undo, so neither is a reason to refuse."""
    if hog_flow.version == proposal.base_version:
        return []
    base_content = base_content_of(hog_flow, proposal)
    content = proposal_changes(proposal, base_content) if content is None else content
    touched_steps = {_item_id(item) for item in content.get("actions") or []} - {None}
    touched_lists = [field for field in PROPOSAL_WHOLE_LIST_FIELDS if field in content]
    touched_fields = [
        field
        for field in content
        if field not in PROPOSAL_MERGE_BY_ID_FIELDS and field not in PROPOSAL_WHOLE_LIST_FIELDS
    ]
    if touched_lists:
        # A whole-list field replaces the list, so any publish since counts.
        return sorted({*touched_steps, *touched_lists, *touched_fields})
    if base_content is None:
        # Without the snapshot the proposal read, "changed since" is unanswerable.
        return sorted({*touched_steps, *touched_fields})
    live_content = hog_flow.content
    base_actions = {_item_id(item): item for item in base_content.get("actions") or []}
    live_actions = {_item_id(item): item for item in live_content.get("actions") or []}
    proposed_actions = {_item_id(item): item for item in content.get("actions") or []}
    moved_steps = [
        step_id
        for step_id in touched_steps
        # A step the proposal adds is only a conflict if that id now exists.
        if not (step_id not in base_actions and step_id not in live_actions)
        and _moved_since(base_actions.get(step_id), live_actions.get(step_id), proposed_actions[step_id])
    ]
    moved_fields = [
        field
        for field in touched_fields
        # These replace the whole value, so a key the proposal does not name still goes with it.
        if base_content.get(field) != live_content.get(field) and live_content.get(field) != content[field]
    ]
    return sorted({*moved_steps, *moved_fields})


def base_content_of(hog_flow: LiveWorkflowContent, proposal: WorkflowProposalRecord) -> dict | None:
    """The workflow as the proposal read it. That is the live workflow while its version has not
    moved; after a publish it is the revision snapshot, which a workflow that has never been
    published under revision tracking may not have."""
    if hog_flow.version == proposal.base_version:
        return hog_flow.content
    revision = HogFlowRevision.objects.filter(hog_flow_id=hog_flow.hog_flow_id, version=proposal.base_version).first()
    return dict(revision.content) if revision is not None else None


def proposal_changes(proposal: WorkflowProposalRecord, base_content: dict | None) -> dict:
    """The proposal's content reduced to what it changes against the workflow as it read it: a
    step keeps only the fields that read differently there, and a step that reads the same drops
    out. A producer that sends a whole step therefore still merges as the one-field change it made,
    and never writes the rest of that step back over a later edit. Without the snapshot the content
    stands as sent."""
    content = dict(proposal.content)
    if base_content is None or "actions" not in content:
        return content
    base_steps = {_item_id(item): item for item in base_content.get("actions") or []}
    changed_steps = []
    for item in content.get("actions") or []:
        base_step = base_steps.get(_item_id(item))
        if not isinstance(item, dict) or base_step is None:
            changed_steps.append(item)
            continue
        changed = _changed_leaves(base_step, {key: value for key, value in item.items() if key != "id"})
        if changed is not _ABSENT:
            changed_steps.append({"id": item["id"], **changed})
    content["actions"] = changed_steps
    return content


_ABSENT = object()


def _changed_leaves(base: Any, patch: Any) -> Any:
    """`patch` without every leaf that already reads the same in `base`, read the way `_deep_merge`
    writes it; `_ABSENT` when nothing is left."""
    if isinstance(patch, dict) and isinstance(base, dict):
        kept = {}
        for key, value in patch.items():
            changed = _changed_leaves(base.get(key), value)
            if changed is not _ABSENT:
                kept[key] = changed
        return kept if kept else _ABSENT
    if patch is None:
        return _ABSENT if base is None else None
    return _ABSENT if patch == base else patch


def _moved_since(base: Any, live: Any, proposed: Any) -> bool:
    """Whether someone changed, since `base`, something the proposal sets, and to a value other than
    the proposed one. Reads the patch the way `_deep_merge` writes it: a dict compares leaf by leaf,
    anything else as one value."""
    if not isinstance(proposed, dict) or base is None or live is None:
        return base != live and live != proposed
    return any(
        _leaf(live, path) != _leaf(base, path) and _leaf(live, path) != _leaf(proposed, path)
        for path in _patch_paths(proposed)
    )


def _patch_paths(patch: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if not isinstance(patch, dict) or not patch:
        return [prefix]
    return [path for key, value in patch.items() for path in _patch_paths(value, (*prefix, key))]


def _leaf(item: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(item, dict) or key not in item:
            return _ABSENT
        item = item[key]
    # A null leaf in a patch deletes the key, so it reads as the key being absent.
    return _ABSENT if item is None else item
