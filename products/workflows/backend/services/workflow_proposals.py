import copy
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.api.app_metrics2 import fetch_app_metric_totals

from products.workflows.backend.facade.contracts import CreatedWorkflowProposal, ProposalChanges, WorkflowProposalRecord
from products.workflows.backend.facade.enums import WorkflowProposalStatus
from products.workflows.backend.metrics import (
    GUARDRAIL_LABELS,
    GUARDRAIL_METRICS,
    HOG_FLOW_VERSION_APP_SOURCE,
    MIN_EVIDENCE_SAMPLE,
    TARGET_CLICK_METRIC,
    TARGET_METRICS,
    TARGET_OPEN_METRIC,
    TARGET_SEND_METRIC,
    TARGET_UNTRACKED_METRIC,
    UNAVAILABLE_GUARDRAILS,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_optimization import HogFlowOptimization
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.models.workflow_proposal import WorkflowProposal
from products.workflows.backend.services.hog_flow_content import deep_merge, snapshot_flow_content

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
    applied_only = status == WorkflowProposal.Status.APPLIED
    ordering = ("-applied_version", "-created_at", "-pk") if applied_only else ("-created_at", "-pk")
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
        existing = (
            WorkflowProposal.objects.filter(hog_flow_id=hog_flow_id, source_id=source_id).first() if source_id else None
        )
        if existing is None:
            raise
        return CreatedWorkflowProposal(proposal=_to_record(existing), created=False)
    return CreatedWorkflowProposal(proposal=_to_record(proposal), created=True)


def lock_proposal(*, team_id: int, proposal_id: UUID) -> WorkflowProposalRecord:
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


# How far past the applied version the after side will look for versions that kept the change.
OUTCOME_VERSION_LIMIT = 20

# Written by the serializer on publish, not by whoever edited the workflow.
DERIVED_STEP_KEYS = frozenset({"bytecode", "order", "transpiled"})


def merge_proposal_content(live_content: dict, proposal_content: dict) -> dict:
    """Live content with the proposal applied. Whole-list fields replace; `actions` merges per step
    and, within a step, per field, so a proposal that rewrites one subject line leaves the rest of
    that email and the rest of the graph exactly as they are now."""
    merged = {**live_content, **proposal_content}
    for field in PROPOSAL_MERGE_BY_ID_FIELDS:
        if field in proposal_content:
            merged[field] = _merge_by_id(live_content.get(field) or [], proposal_content[field] or [])
    return merged


def _merge_by_id(live_items: list, changed_items: list) -> list:
    """Merge each changed step into the live step with the same id, field by field, the way the
    graph API's `update_action` does: a producer sends the fields it changes and nothing else, so a
    step can never lose its template inputs to a payload that only carried a subject line."""
    changed_by_id = {item["id"]: item for item in changed_items if isinstance(item, dict) and "id" in item}
    merged = []
    for item in live_items:
        patch = changed_by_id.pop(item_id(item), None)
        merged.append(deep_merge(copy.deepcopy(item), patch) if patch is not None else item)
    # Anything left names a step the workflow does not have yet, so the proposal is adding it whole.
    merged.extend(changed_by_id.values())
    return merged


def item_id(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else None


def describe_steps(hog_flow: HogFlow, step_ids: list[str]) -> list[str]:
    """Step names for a person to read. A step deleted since has no name left, so it keeps its id,
    and a field name is already readable."""
    names = {item_id(item): item.get("name") for item in snapshot_flow_content(hog_flow).get("actions") or []}
    return [names.get(step_id) or step_id for step_id in step_ids]


def conflicting_parts(hog_flow: HogFlow, proposal: WorkflowProposal, content: Optional[dict] = None) -> list[str]:
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
    touched_steps = {item_id(item) for item in content.get("actions") or []} - {None}
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
    live_content = snapshot_flow_content(hog_flow)
    base_actions = {item_id(item): item for item in base_content.get("actions") or []}
    live_actions = {item_id(item): item for item in live_content.get("actions") or []}
    proposed_actions = {item_id(item): item for item in content.get("actions") or []}
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


def base_content_of(hog_flow: HogFlow, proposal: WorkflowProposal) -> dict | None:
    """The workflow as the proposal read it. That is the live workflow while its version has not
    moved; after a publish it is the revision snapshot, which a workflow that has never been
    published under revision tracking may not have."""
    if hog_flow.version == proposal.base_version:
        return snapshot_flow_content(hog_flow)
    revision = HogFlowRevision.objects.filter(hog_flow=hog_flow, version=proposal.base_version).first()
    return dict(revision.content) if revision is not None else None


def proposal_changes(proposal: WorkflowProposal, base_content: dict | None) -> dict:
    """The proposal's content reduced to what it changes against the workflow as it read it: a
    step keeps only the fields that read differently there, and a step that reads the same drops
    out. A producer that sends a whole step therefore still merges as the one-field change it made,
    and never writes the rest of that step back over a later edit. Without the snapshot the content
    stands as sent."""
    content = dict(proposal.content)
    if base_content is None or "actions" not in content:
        return content
    base_steps = {item_id(item): item for item in base_content.get("actions") or []}
    changed_steps = []
    for item in content.get("actions") or []:
        base_step = base_steps.get(item_id(item))
        if not isinstance(item, dict) or base_step is None:
            changed_steps.append(item)
            continue
        changed = _changed_leaves(base_step, {key: value for key, value in item.items() if key != "id"})
        if changed is not _ABSENT:
            changed_steps.append({"id": item["id"], **changed})
    content["actions"] = changed_steps
    return content


_ABSENT = object()


# Wrapper keys every step input carries. A person reads "email > subject", not the path to it.
SILENT_PATH_SEGMENTS = frozenset({"config", "inputs", "value"})

# Long bodies and HTML would drown the list; the field name plus a taste of the value is the point.
CHANGE_VALUE_LIMIT = 120


def _describe_value(value: Any) -> Optional[str]:
    if value is _ABSENT or value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= CHANGE_VALUE_LIMIT else f"{text[:CHANGE_VALUE_LIMIT]}…"


def _describe_path(path: Sequence[str]) -> str:
    spoken = [segment for segment in path if segment not in SILENT_PATH_SEGMENTS]
    return " › ".join(spoken or list(path))


# `trigger` is derived from the trigger action, so a change to it already reads as a step change.
# Counting it again at workflow level reads as an edit nobody made.
DERIVED_WORKFLOW_FIELDS = frozenset({"trigger"})


def describe_version_changes(previous: dict, current: dict, proposed: Mapping) -> list[dict]:
    """Every field this version published differently from the one before it.

    Derived keys are skipped: publishing recompiles inputs, and nobody edited those.
    """

    def from_suggestion(key: tuple, value: Any) -> bool:
        # Membership first: a cleared field reads as absent, and so does a field the proposal never
        # named, so comparing values alone calls an unrelated clear a suggested change.
        return key in proposed and proposed[key] == value

    changes: list[dict] = []
    was_steps = {item_id(item): item for item in previous.get("actions") or []}
    now_steps = {item_id(item): item for item in current.get("actions") or []}
    for step in current.get("actions") or []:
        step_id = item_id(step)
        was = was_steps.get(step_id)
        if was is None:
            changes.append(
                {
                    "step_name": step.get("name") or step_id,
                    "field": "step added",
                    "before": None,
                    "after": _describe_value(step.get("type")),
                    "from_suggestion": any(key[0] == step_id for key in proposed),
                }
            )
            continue
        paths = {
            path
            for item in (step, was)
            for path in _patch_paths({key: value for key, value in item.items() if key != "id"})
        }
        for path in sorted(paths):
            if path[-1] in DERIVED_STEP_KEYS:
                continue
            after, before = _leaf(step, path), _leaf(was, path)
            if after == before:
                continue
            changes.append(
                {
                    "step_name": step.get("name") or step_id,
                    "field": _describe_path(path),
                    "before": _describe_value(before),
                    "after": _describe_value(after),
                    "from_suggestion": from_suggestion((step_id, path), after),
                }
            )
    for step_id, was in was_steps.items():
        if step_id in now_steps:
            continue
        changes.append(
            {
                "step_name": was.get("name") or step_id,
                "field": "step removed",
                "before": _describe_value(was.get("type")),
                "after": None,
                "from_suggestion": False,
            }
        )
    for field in sorted({*current, *previous}):
        if field in PROPOSAL_MERGE_BY_ID_FIELDS or field in DERIVED_WORKFLOW_FIELDS:
            continue
        value, before = current.get(field, _ABSENT), previous.get(field, _ABSENT)
        if value == before:
            continue
        changes.append(
            {
                "step_name": None,
                "field": _describe_path([field]),
                "before": _describe_value(before),
                "after": _describe_value(value),
                "from_suggestion": from_suggestion((None, (field,)), value),
            }
        )
    return changes


def target_metric_in(evidence: Any) -> str:
    """The metric the suggestion aimed at. Anything the surfaces cannot read is measured on opens."""
    named = evidence.get("metric") if isinstance(evidence, dict) else None
    return named if named in TARGET_METRICS else TARGET_OPEN_METRIC


def target_metric_of(proposal: WorkflowProposal) -> str:
    return target_metric_in(proposal.evidence)


def outcome_from_totals(totals: Mapping[str, float], version: int, target: str = TARGET_OPEN_METRIC) -> dict:
    sends = int(totals.get(TARGET_SEND_METRIC, 0))
    # Untracked sends can never record an open, so opens read against tracked sends; guardrails keep every send.
    tracked_sends = max(0, sends - int(totals.get(TARGET_UNTRACKED_METRIC, 0)))

    def rate(count: int, label: str, denominator: int) -> dict:
        return {
            "metric": label,
            "value": (count / denominator) if denominator else None,
            "n": denominator,
            "below_minimum_sample": denominator < MIN_EVIDENCE_SAMPLE,
        }

    def reading(metric: str) -> dict:
        name, over_tracked, label = TARGET_METRICS[metric]
        return rate(int(totals.get(name, 0)), label, tracked_sends if over_tracked else sends)

    # The rate to read beside the target: opens, unless opens are the target.
    secondary = TARGET_CLICK_METRIC if target == TARGET_OPEN_METRIC else TARGET_OPEN_METRIC
    return {
        "version": version,
        "versions": [version],
        "target": reading(target),
        "secondary": reading(secondary),
        # Same denominator as opens: a send with tracking off can record neither.
        "click_through": reading(TARGET_CLICK_METRIC),
        "guardrails": [rate(int(totals.get(name, 0)), GUARDRAIL_LABELS[name], sends) for name in GUARDRAIL_METRICS],
    }


def carries_proposal_change(content: dict, changes: dict) -> bool:
    """Whether this published content still holds every value the proposal set."""
    steps = {item_id(item): item for item in content.get("actions") or []}
    for item in changes.get("actions") or []:
        step = steps.get(item_id(item))
        patch = {key: value for key, value in item.items() if key != "id"}
        if step is None or _changed_leaves(step, patch) is not _ABSENT:
            return False
    for field, value in changes.items():
        if field in PROPOSAL_MERGE_BY_ID_FIELDS:
            continue
        if _changed_leaves(content.get(field), value) is not _ABSENT:
            return False
    return True


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


def as_the_serializer_stores_it(content: dict, validated: Mapping) -> dict:
    """The proposal's own values, in the shape a publish would write them.

    A field validator can rewrite what a producer sent: a bare `output_variable` string is stored as
    `{"key": ...}`. The published workflow then holds the rewritten shape, so a raw value kept here
    would make every later comparison read the change as already gone.
    """
    aligned = deepcopy(content)
    validated_steps = {item_id(item): item for item in validated.get("actions") or []}
    for item in aligned.get("actions") or []:
        step = validated_steps.get(item_id(item))
        if step is None:
            continue
        for path in _patch_paths({key: value for key, value in item.items() if key != "id"}):
            stored = _leaf(step, path)
            if stored is not _ABSENT:
                _write_leaf(item, path, stored)
    for field in list(aligned):
        if field in PROPOSAL_MERGE_BY_ID_FIELDS or field not in validated:
            continue
        aligned[field] = validated[field]
    return aligned


def _write_leaf(item: dict, path: tuple[str, ...], value: Any) -> None:
    for key in path[:-1]:
        nested = item.get(key)
        if not isinstance(nested, dict):
            return
        item = nested
    item[path[-1]] = value


def unstage_proposals_for_flow(hog_flow: HogFlow) -> None:
    """Put back in the queue any approved suggestion whose change the draft no longer carries.

    Approved means one thing here: this suggestion's change sits in the draft. Discarding the draft,
    restoring a revision, approving a different suggestion or editing over the draft can take that
    change out again, so the suggestion is pending again - and publish, which reads approved as
    "this is what shipped", must not record it as applied against a version that never carried it.
    An edit that leaves the change in place, elsewhere on the same step or not, changes nothing here.
    """
    approved = WorkflowProposal.objects.filter(hog_flow=hog_flow, status=WorkflowProposal.Status.APPROVED)
    draft = hog_flow.draft
    gone = [
        proposal.id
        for proposal in approved
        if draft is None
        or merge_proposal_content(draft, proposal_changes(proposal, base_content_of(hog_flow, proposal))) != draft
    ]
    if gone:
        WorkflowProposal.objects.filter(team_id=hog_flow.team_id, id__in=gone).update(
            status=WorkflowProposal.Status.SUGGESTED, resolved_at=None, resolved_by=None
        )


def outcome_versions(hog_flow: HogFlow, proposal: WorkflowProposal, carrying: Sequence[int] = ()) -> list[int]:
    """The versions the card charts: the one the suggestion was written against, the one it went
    live as, and everything published since, so a later edit is visible as its own point.

    A version the after side sums is always in here. Past the recent range it would otherwise be
    fetched for nobody and counted as zero, which reads as a change that stopped working.
    """
    newest = hog_flow.version or proposal.base_version
    oldest = min(proposal.base_version, proposal.applied_version or proposal.base_version)
    pinned = {oldest, proposal.base_version, *carrying}
    if proposal.applied_version is not None:
        pinned.add(proposal.applied_version)
    return sorted({*range(max(oldest, newest - OUTCOME_VERSION_LIMIT + 1), newest + 1), *pinned})


def version_history(hog_flow: HogFlow, proposal: WorkflowProposal, versions: list[int]) -> dict[int, dict]:
    """What each version changed against the one before it, and who published it.

    A version's numbers hold every change that shipped in it, and no window separates them, so
    the card says what else was in there rather than leaving a move unexplained.
    """
    if not versions:
        return {}
    # Each revision holds a whole workflow snapshot, so a suggestion filed against v1 of a
    # workflow on v1000 would read a thousand of them to describe twenty.
    wanted = set(versions) | {version - 1 for version in versions}
    revisions = {
        revision.version: revision
        for revision in HogFlowRevision.objects.filter(hog_flow=hog_flow, version__in=sorted(wanted))
        .order_by("version")
        .select_related("created_by")
    }
    contents = {version: revision.content for version, revision in revisions.items()}
    if hog_flow.version in versions:
        contents.setdefault(hog_flow.version, snapshot_flow_content(hog_flow))
    changed = proposal_changes(proposal, base_content_of(hog_flow, proposal))
    proposed = {
        (item_id(item), path): _leaf(item, path)
        for item in changed.get("actions") or []
        for path in _patch_paths({key: value for key, value in item.items() if key != "id"})
    } | {(None, (field,)): value for field, value in changed.items() if field not in PROPOSAL_MERGE_BY_ID_FIELDS}
    history: dict[int, dict] = {}
    for version in versions:
        previous, current = contents.get(version - 1), contents.get(version)
        changes = (
            describe_version_changes(previous, current, proposed)
            if previous is not None and current is not None
            else []
        )
        revision = revisions.get(version)
        history[version] = {
            "changes": changes,
            "other_changes": any(not change["from_suggestion"] for change in changes),
            "published_at": revision.created_at if revision else None,
            "published_by": revision.created_by if revision else None,
        }
    return history


def version_totals(hog_flow: HogFlow, versions: list[int], step_id: Optional[str]) -> dict[int, dict]:
    """Raw metric counts per version. Each version's series only ever collects while that
    version is live, so there is no window to choose."""
    return {
        version: fetch_app_metric_totals(
            team_id=hog_flow.team_id,
            app_source=HOG_FLOW_VERSION_APP_SOURCE,
            app_source_id=f"{hog_flow.id}/{version}",
            breakdown_by="name",
            # Scoped to the step the suggestion names; several email steps would otherwise share one denominator.
            instance_id=step_id or None,
            name=[
                TARGET_SEND_METRIC,
                TARGET_OPEN_METRIC,
                TARGET_CLICK_METRIC,
                TARGET_UNTRACKED_METRIC,
                *GUARDRAIL_METRICS,
            ],
        ).totals
        for version in versions
    }


def versions_carrying_change(hog_flow: HogFlow, proposal: WorkflowProposal) -> tuple[list[int], Optional[int]]:
    """The versions the change ran on, and the version that ended it.

    A later publish keeps the change unless it touches what the suggestion set, so the after side
    runs on across those versions. The first version that sets one of those values to something
    else ends the comparison: what shipped after that is a different change, not this one.
    """
    applied = proposal.applied_version
    if applied is None:
        return [], None
    changes = proposal_changes(proposal, base_content_of(hog_flow, proposal))
    contents = {
        revision.version: revision.content
        for revision in HogFlowRevision.objects.filter(hog_flow=hog_flow, version__gte=applied).order_by("version")[
            :OUTCOME_VERSION_LIMIT
        ]
    }
    # One revision row per publish, so a gap between the last one read and the live version means
    # the slice stopped short. Reading the live version across that gap would call the change
    # survived without looking at the publishes in between.
    live_version = hog_flow.version or applied
    if live_version >= applied and (not contents or live_version <= max(contents) + 1):
        contents.setdefault(live_version, snapshot_flow_content(hog_flow))
    carrying: list[int] = []
    for version in sorted(contents):
        if not carries_proposal_change(contents[version], changes):
            return carrying or [applied], version
        carrying.append(version)
    return carrying or [applied], None


def version_outcome(
    *,
    team_id: int,
    hog_flow_id: UUID,
    versions: Sequence[Optional[int]],
    after: datetime,
    step_id: Optional[str] = None,
    target: str = TARGET_OPEN_METRIC,
) -> Optional[dict]:
    read = [version for version in versions if version is not None]
    if not read:
        return None
    totals: dict[str, float] = {}
    for version in read:
        # Scoped to the step the suggestion names; several email steps would otherwise share one denominator.
        per_version = fetch_app_metric_totals(
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
        for name, count in per_version.items():
            totals[name] = totals.get(name, 0) + count
    return {**outcome_from_totals(totals, read[0], target), "versions": read}


def _proposal_outcome(hog_flow: HogFlow, proposal: WorkflowProposal) -> dict:
    """What an applied suggestion did: per-version readings, and the before and after sides."""
    carrying, ended_at = versions_carrying_change(hog_flow, proposal)
    charted = outcome_versions(hog_flow, proposal, carrying)
    totals = version_totals(hog_flow, charted, proposal.step_id)
    history = version_history(hog_flow, proposal, charted)
    target = target_metric_of(proposal)
    versions = [
        {
            **outcome_from_totals(counts, version, target),
            "applied": version == proposal.applied_version,
            "proposed_against": version == proposal.base_version,
            "carries_change": version in carrying,
            **history.get(version, {"other_changes": False, "changes": []}),
        }
        for version, counts in sorted(totals.items())
    ]
    after_totals: dict[str, float] = {}
    for version in carrying:
        for name, count in totals.get(version, {}).items():
            after_totals[name] = after_totals.get(name, 0) + count
    return {
        "versions": versions,
        "before": outcome_from_totals(totals.get(proposal.base_version, {}), proposal.base_version, target),
        "after": (
            {**outcome_from_totals(after_totals, carrying[0], target), "versions": carrying} if carrying else None
        ),
        "change_ended_at_version": ended_at,
        "unavailable_guardrails": list(UNAVAILABLE_GUARDRAILS),
    }


def _load(team_id: int, hog_flow_id: UUID, proposal_id: UUID) -> tuple[HogFlow, WorkflowProposal]:
    hog_flow = HogFlow.objects.get(team_id=team_id, pk=hog_flow_id)
    proposal = WorkflowProposal.objects.get(team_id=team_id, hog_flow_id=hog_flow_id, pk=proposal_id)
    return hog_flow, proposal


def proposal_outcome(*, team_id: int, hog_flow_id: UUID, proposal_id: UUID) -> dict:
    """What an applied suggestion did: per-version readings, and the before and after sides."""
    return _proposal_outcome(*_load(team_id, hog_flow_id, proposal_id))


def proposal_conflicts(*, team_id: int, hog_flow_id: UUID, proposal_id: UUID) -> list[str]:
    """Parts of the workflow the suggestion changes that someone else changed since it was written."""
    return conflicting_parts(*_load(team_id, hog_flow_id, proposal_id))


def staged_proposal_changes(*, team_id: int, hog_flow_id: UUID, proposal_id: UUID) -> ProposalChanges:
    """What approving the suggestion would stage, or the steps in the way when it no longer applies."""
    hog_flow, proposal = _load(team_id, hog_flow_id, proposal_id)
    changes = proposal_changes(proposal, base_content_of(hog_flow, proposal))
    conflicts = conflicting_parts(hog_flow, proposal, changes)
    return ProposalChanges(changes=changes, conflicts=describe_steps(hog_flow, conflicts))


def unstage_workflow_proposals(*, team_id: int, hog_flow_id: UUID) -> None:
    """Re-queues approved suggestions the saved draft no longer carries. Call it after the draft is saved."""
    unstage_proposals_for_flow(HogFlow.objects.get(team_id=team_id, pk=hog_flow_id))


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
