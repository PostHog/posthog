from collections.abc import Callable, Mapping
from copy import copy
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.models import Team, User
from posthog.ph_client import feature_enabled_or_false

from products.workflows.backend.facade.contracts import (
    StatusChange,
    WorkflowEditState,
    WorkflowEvent,
    WorkflowHasNoDraft,
    WorkflowStale,
    WorkflowWriteResult,
)
from products.workflows.backend.facade.enums import HogFlowOriginProduct, HogFlowScheduleStatus, HogFlowState
from products.workflows.backend.models.hog_flow.hog_flow import BILLABLE_ACTION_TYPES, ROW_SCOPED_TRIGGER_TYPES, HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.services.action_redirects import compute_action_redirects
from products.workflows.backend.services.hog_flow_content import DRAFT_CONTENT_FIELDS, snapshot_flow_content
from products.workflows.backend.services.hog_flow_reads import to_edit_state
from products.workflows.backend.services.hog_flow_secrets import (
    TemplateCache,
    strip_content_secrets,
    strip_secrets_from_content,
)
from products.workflows.backend.services.integration_usage import (
    email_senders_of,
    lock_unverified_senders,
    waiting_flows_using,
)
from products.workflows.backend.services.timing_reschedule import (
    get_all_timing_action_ids,
    get_timing_reschedule_action_ids,
)
from products.workflows.backend.services.workflow_proposals import (
    apply_approved_proposals_for_flow,
    unstage_workflow_proposals,
)
from products.workflows.backend.tasks.hog_flows import reschedule_hog_flow_timing

EMAIL_DOMAIN_WIZARD_FLAG = "workflows-email-domain-wizard"

ActivatedBy = Literal["user", "domain_verified"]


def field_values(flow: HogFlow) -> dict[str, object]:
    return {field.attname: getattr(flow, field.attname) for field in flow._meta.concrete_fields}


def _sender_check_rolled_out(team_id: int, user_id: Optional[int]) -> bool:
    user = User.objects.filter(pk=user_id).only("distinct_id").first() if user_id else None
    if user is None:
        return False
    team = Team.objects.only("uuid", "organization_id").get(pk=team_id)
    organization_id, project_id = str(team.organization_id), str(team.uuid)
    try:
        return feature_enabled_or_false(
            EMAIL_DOMAIN_WIZARD_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        return False


def _unverified_senders_of(flow: HogFlow, user_id: Optional[int]) -> frozenset[int]:
    # Transactional email workflows refuse an unverified sender on their own, so they never wait for one.
    if flow.origin_product == HogFlowOriginProduct.TRANSACTIONAL_EMAILS:
        return frozenset()
    senders = email_senders_of(flow)
    if not senders or not _sender_check_rolled_out(flow.team_id, user_id):
        return frozenset()
    return lock_unverified_senders(team_id=flow.team_id, sender_ids=senders)


def _seconds_waiting(flow: HogFlow, now: datetime) -> int:
    return int((now - flow.enable_requested_at).total_seconds()) if flow.enable_requested_at else 0


def _request_enable(flow: HogFlow, *, user_id: Optional[int]) -> tuple[WorkflowEvent, ...]:
    """Apply a person's Enable to the locked or unsaved row and return its events. The caller saves it."""
    now = timezone.now()
    unverified = _unverified_senders_of(flow, user_id)
    current = HogFlowState.WAITING_FOR_DOMAIN if unverified else HogFlowState.ACTIVE
    flow.status = current
    flow.enable_requested_at = now
    flow.enable_requested_by_id = user_id
    if current == HogFlowState.ACTIVE:
        flow.went_live_at = now
    events = [
        WorkflowEvent(
            name="hog_flow_enable_requested",
            workflow_id=flow.id,
            user_id=user_id,
            properties={"outcome": current.value, "unverified_sender_count": len(unverified)},
        )
    ]
    if current == HogFlowState.ACTIVE:
        events.append(_activated_event(flow, activated_by="user", now=now))
    return tuple(events)


def _apply_enable(
    target: HogFlow, locked: HogFlow, data: dict, user_id: Optional[int]
) -> tuple[dict, tuple[WorkflowEvent, ...]]:
    """Apply a person's Enable to ``target``, the row ``locked`` holds. Returns the fields left to save and the
    events. An active or archived workflow keeps its status and gets no events."""
    if locked.status in (HogFlowState.ACTIVE, HogFlowState.ARCHIVED):
        return _without_status(data), ()
    if "actions" in data:
        target.actions = data["actions"]
    return _without_status(data), _request_enable(target, user_id=user_id)


def _activated_event(flow: HogFlow, *, activated_by: ActivatedBy, now: datetime) -> WorkflowEvent:
    return WorkflowEvent(
        name="hog_flow_activated",
        workflow_id=flow.id,
        user_id=flow.enable_requested_by_id,
        properties={
            "activated_by": activated_by,
            "seconds_waiting": _seconds_waiting(flow, now),
            "enable_requested_at": flow.enable_requested_at.isoformat() if flow.enable_requested_at else None,
            "edges_count": len(flow.edges or []),
            "actions_count": len(flow.actions or []),
        },
    )


def _go_live_once_senders_verified(flow: HogFlow, *, activated_by: ActivatedBy) -> Optional[StatusChange]:
    """Take a waiting workflow live when none of its email senders is unverified. Ignores the flag, because
    the sender check already ran when the person enabled it. The caller saves the row."""
    if lock_unverified_senders(team_id=flow.team_id, sender_ids=email_senders_of(flow)):
        return None
    now = timezone.now()
    flow.status = HogFlowState.ACTIVE
    flow.went_live_at = now
    return StatusChange(
        workflow_id=flow.id,
        previous=HogFlowState.WAITING_FOR_DOMAIN,
        current=HogFlowState.ACTIVE,
        events=(_activated_event(flow, activated_by=activated_by, now=now),),
    )


def _events_on_leaving(flow: HogFlow) -> tuple[WorkflowEvent, ...]:
    """Events for a workflow that a person turns off, archives or deletes, read before the change."""
    if flow.status != HogFlowState.WAITING_FOR_DOMAIN:
        return ()
    return (
        WorkflowEvent(
            name="hog_flow_waiting_cancelled",
            workflow_id=flow.id,
            user_id=flow.enable_requested_by_id,
            properties={"seconds_waiting": _seconds_waiting(flow, timezone.now())},
        ),
    )


def _without_status(validated_data: dict) -> dict:
    return {key: value for key, value in validated_data.items() if key != "status"}


def create_workflow(*, team_id: int, user_id: Optional[int], validated_data: dict) -> WorkflowWriteResult:
    with transaction.atomic():
        data = dict(validated_data)
        if "actions" in data:
            data["encrypted_inputs"] = strip_secrets_from_content(data, template_cache={})
        instance = HogFlow(team_id=team_id, created_by_id=user_id, **data)
        events: tuple[WorkflowEvent, ...] = ()
        if instance.status == HogFlowState.ACTIVE:
            events = _request_enable(instance, user_id=user_id)
        instance.save(force_insert=True)
        HogFlowRevision.objects.create(
            team_id=team_id,
            hog_flow=instance,
            version=instance.version,
            content=snapshot_flow_content(instance),
            created_by_id=user_id,
        )
    return WorkflowWriteResult(previous={}, current=field_values(instance), events=events)


def destroy_workflow(*, team_id: int, hog_flow_id: UUID) -> tuple[WorkflowEvent, ...]:
    with transaction.atomic():
        flow = HogFlow.objects.select_for_update().get(team_id=team_id, pk=hog_flow_id)
        events = _events_on_leaving(flow)
        flow.delete()
    return events


def enable(*, team_id: int, hog_flow_id: UUID, user_id: int, validated_data: Mapping[str, object]) -> StatusChange:
    """A person's Enable: save ``active`` when every email sender is verified, else ``waiting_for_domain``.
    ``validated_data`` is the activation the serializer validated. Leaves an active or archived workflow alone."""
    with transaction.atomic():
        locked = HogFlow.objects.select_for_update().get(team_id=team_id, pk=hog_flow_id)
        previous = HogFlowState(locked.status)
        data, events = _apply_enable(locked, locked, dict(validated_data), user_id)
        if events:
            _save_live(locked, data)
    return StatusChange(workflow_id=locked.id, previous=previous, current=HogFlowState(locked.status), events=events)


def enable_waiting(*, team_id: int, sender_ids: frozenset[int]) -> tuple[StatusChange, ...]:
    """Take live each waiting workflow that sends from ``sender_ids`` and has no unverified sender left."""
    changes = []
    for hog_flow_id in waiting_flows_using(team_id=team_id, sender_ids=sender_ids):
        with transaction.atomic():
            locked = (
                HogFlow.objects.select_for_update()
                .filter(team_id=team_id, pk=hog_flow_id, status=HogFlowState.WAITING_FOR_DOMAIN)
                .first()
            )
            if locked is None:
                continue
            before = copy(locked)
            change = _go_live_once_senders_verified(locked, activated_by="domain_verified")
            if change is None:
                continue
            locked.save()
        _reschedule_timing_edits(team_id, before, locked)
        changes.append(change)
    return tuple(changes)


def disable(*, team_id: int, hog_flow_id: UUID) -> StatusChange:
    """Turn an active or waiting workflow back into a draft."""
    with transaction.atomic():
        locked = HogFlow.objects.select_for_update().get(team_id=team_id, pk=hog_flow_id)
        previous = HogFlowState(locked.status)
        if previous not in (HogFlowState.ACTIVE, HogFlowState.WAITING_FOR_DOMAIN):
            return StatusChange(workflow_id=locked.id, previous=previous, current=previous, events=())
        events = _events_on_leaving(locked)
        _save_live(locked, {"status": HogFlowState.DRAFT})
    return StatusChange(workflow_id=locked.id, previous=previous, current=HogFlowState.DRAFT, events=events)


def trigger_has_audience(trigger: Optional[dict]) -> bool:
    """Whether a dispatch of this workflow fans out to persons matched by the trigger's filters.

    Only the batch trigger does. A schedule trigger fires one person-less run, so there is no
    audience to preview and no blast-radius token to demand.
    """
    return (trigger or {}).get("type") == "batch"


def publish_confirm_value(*, hog_flow_id: UUID, draft_updated_at: Optional[datetime]) -> str:
    draft_stamp = draft_updated_at.isoformat() if draft_updated_at else ""
    return f"{hog_flow_id}:{draft_stamp}"


def _without_bytecode_contracts(node: Any) -> Any:
    # Every recompile writes the current runtime's stamp beside each filter and input bytecode. A flow
    # stored before stamping, or under an older runtime, gets a new stamp on its next save even when
    # nobody changed it, so the revision comparison must not count the stamp as content. A stamp only
    # ever sits next to a `bytecode` key, so a same-named key inside a person's own JSON value stays
    # content and still versions the flow.
    if isinstance(node, dict):
        derived = "bytecode" in node
        return {
            key: _without_bytecode_contracts(value)
            for key, value in node.items()
            if not (derived and key == "bytecode_contract")
        }
    if isinstance(node, list):
        return [_without_bytecode_contracts(item) for item in node]
    return node


def _parse_stamp(raw: Optional[str]) -> Optional[datetime]:
    stamp = parse_datetime(raw) if raw else None
    # A timezone-less timestamp parses naive; comparing it to the tz-aware stored updated_at would
    # raise TypeError (500). Assume UTC so callers can send a bare ISO string.
    if stamp is not None and timezone.is_naive(stamp):
        stamp = timezone.make_aware(stamp)
    return stamp


def _save_live(instance: HogFlow, validated_data: dict, **overrides: object) -> None:
    # Move secret function inputs out of the live `actions` into
    # encrypted_inputs when the write carries actions (a metadata-only update must not touch stored
    # secrets), then save the whole row.
    data = {**validated_data, **overrides}
    if "actions" in data:
        data["encrypted_inputs"] = strip_secrets_from_content(data, template_cache={})
    for attr, value in data.items():
        setattr(instance, attr, value)
    instance.save()


def save_validated_workflow(*, team_id: int, hog_flow_id: UUID, validated_data: dict) -> None:
    """Write a workflow's validated fields to the live row, with no draft routing, revision bump or
    follow-ups. For callers outside a request: enabling a workflow and the bytecode refresh."""
    # The save writes every column. Lock the read so that a concurrent write, such as a staff email
    # sending pause, either lands before this read or waits for this save, and is never overwritten.
    with transaction.atomic():
        _save_live(HogFlow.objects.select_for_update().get(team_id=team_id, pk=hog_flow_id), validated_data)


def _derive_from_locked_graph(locked: HogFlow, validated_data: dict) -> dict:
    # HogFlowSerializer.validate derives trigger, billable_action_types and exit_condition from the
    # actions it read before the row lock. A write without actions keeps the locked row's actions, and a
    # concurrent graph write can change those actions before the lock. Derive these fields again from the
    # locked actions, so that the save does not pair the new graph with fields derived from the old graph.
    if "actions" in validated_data:
        return validated_data
    actions = locked.actions or []
    derived = dict(validated_data)
    trigger_action = next((action for action in actions if action.get("type") == "trigger"), None)
    if "trigger" in derived and trigger_action is not None:
        derived["trigger"] = trigger_action.get("config")
    if "exit_condition" in derived:
        # validate forces exit_only_at_end when the trigger it read is row-scoped. Apply that rule to the
        # locked trigger instead. When only the old trigger forced the value, keep the locked row's value.
        if (derived.get("trigger") or {}).get("type") in ROW_SCOPED_TRIGGER_TYPES:
            derived["exit_condition"] = HogFlow.ExitCondition.ONLY_AT_END
        elif (validated_data.get("trigger") or {}).get("type") in ROW_SCOPED_TRIGGER_TYPES:
            del derived["exit_condition"]
    if "billable_action_types" in derived:
        derived["billable_action_types"] = sorted(
            {action.get("type", "") for action in actions if action.get("type") in BILLABLE_ACTION_TYPES}
        )
    return derived


def _refresh_action_redirects(target: HogFlow, old: HogFlow, new_actions: Optional[list]) -> None:
    # Skip-forward for deleted steps: refresh the redirect map whenever a live graph write is about
    # to land, while both the old graph (`old`, the locked pre-write row) and the new actions are in
    # hand. Must run before the save so the map persists in the same write, transaction,
    # and worker reload as the graph it describes.
    # No status gate: disabling a flow doesn't purge its parked runs (the worker only cancels them
    # if they wake while the flow is still disabled), so a step deleted during a disable/re-enable
    # window needs its redirect recorded just like one deleted live.
    if new_actions is None:
        return
    target.action_redirects = compute_action_redirects(
        old.actions or [], old.edges or [], new_actions, old.action_redirects
    )


def _stage_revision_bump(instance: HogFlow, before: HogFlow, validated_data: dict) -> bool:
    # Revision history: only live-content changes get a version. Compared pre-save so the bumped
    # version lands in the same UPDATE (and worker reload) as the content it describes. The
    # serializer injects derived fields (trigger, billable_action_types) into every validated
    # payload, so a status/metadata-only write compares equal here and stays unversioned.
    raw_old = snapshot_flow_content(before)
    raw_new = {
        **raw_old,
        **{field: validated_data[field] for field in DRAFT_CONTENT_FIELDS if field in validated_data},
    }
    # Compare secret-free on both sides. `raw_new` still carries the plaintext secrets validation
    # recovered into `actions` (stripping happens later in the save), while `before` is the persisted
    # stripped snapshot; without this a secret-bearing flow would bump on every actions-carrying save.
    template_cache: TemplateCache = {}
    old_content = _without_bytecode_contracts(strip_content_secrets(raw_old, template_cache))
    new_content = _without_bytecode_contracts(strip_content_secrets(raw_new, template_cache))
    if new_content == old_content:
        return False
    instance.version = (before.version or 0) + 1
    return True


def _append_revisions(team_id: int, user_id: Optional[int], instance: HogFlow, before: HogFlow) -> None:
    # Must run inside the same transaction as the content write it snapshots. On the first
    # tracked write, also snapshot the outgoing live content so the state before any tracked
    # change is always available to roll back to (there's no backfill).
    if not HogFlowRevision.objects.filter(team_id=team_id, hog_flow=instance).exists():
        HogFlowRevision.objects.create(
            team_id=team_id,
            hog_flow=instance,
            version=before.version,
            content=snapshot_flow_content(before),
            created_by=None,
        )
    HogFlowRevision.objects.create(
        team_id=team_id,
        hog_flow=instance,
        version=instance.version,
        content=snapshot_flow_content(instance),
        created_by_id=user_id,
    )


def _write_draft(instance: HogFlow, locked: HogFlow, validated_data: dict) -> None:
    # The draft is always a full content snapshot (live config as the base, staged draft on top,
    # this edit's validated fields last) so publish is a plain copy with no merge logic.
    draft = {**snapshot_flow_content(locked), **(locked.draft or {})}
    for field in DRAFT_CONTENT_FIELDS:
        if field in validated_data:
            draft[field] = validated_data[field]

    # Keep secrets out of the draft snapshot too. When this edit carried the full action set (its
    # secrets recovered in-place), split them into the draft's own encrypted column and strip the
    # snapshot; otherwise the draft's secrets are unchanged. Publish/restore re-attach from here.
    draft_encrypted_inputs = locked.draft_encrypted_inputs
    if "actions" in validated_data:
        draft_encrypted_inputs = strip_secrets_from_content(draft, template_cache={})

    instance.draft = draft
    instance.draft_updated_at = timezone.now()
    instance.draft_encrypted_inputs = draft_encrypted_inputs
    instance.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

    # An edit over an approved draft may undo the suggestion, and publish reads approved as shipped.
    unstage_workflow_proposals(team_id=instance.team_id, hog_flow_id=instance.pk)


def _reschedule_timing_edits(team_id: int, before: HogFlow, after: HogFlow) -> None:
    """Kick off a reschedule sweep of parked runs when a go-live config change could move
    their wake times earlier or change what they resolve to (issue #66380): shortened
    delays, moved wait windows, edited wait conditions, and deleted timing steps (whose
    parked runs should skip forward or exit now, not at their old wake time).

    Called wherever the LIVE config changes - a direct save (the builder path, where save
    is go-live), the graph endpoint, or publish - and never for draft writes, which don't
    touch what runs execute. Deliberately called AFTER the writing transaction, so the diff and
    the enqueue never extend the select_for_update row-lock hold. on_commit outside an atomic
    block runs the enqueue immediately, and in tests (where an outer transaction wraps the
    request) it defers to that commit.
    """
    if after.status != HogFlow.State.ACTIVE:
        return
    if before.status != HogFlow.State.ACTIVE:
        # Re-enable: runs parked during the prior active period survive a disable (cancelled
        # lazily, at wake, only while the flow is inactive), and timing edits made while
        # inactive never swept - so converge every timing step rather than diffing against a
        # baseline that may predate any number of unswept edits.
        action_ids = get_all_timing_action_ids(after.actions)
    else:
        action_ids = get_timing_reschedule_action_ids(before.actions, after.actions)
    if not action_ids:
        return
    hog_flow_id = str(after.id)
    transaction.on_commit(
        lambda: reschedule_hog_flow_timing.delay(team_id=team_id, hog_flow_id=hog_flow_id, action_ids=action_ids)
    )


def _pause_schedules_on_audience_change(before: HogFlow, after: HogFlow) -> int:
    """Pause every active schedule when the audience a batch dispatch fans out to changes.

    The scheduler reads the live trigger at fire time, so each firing broadcasts to whatever
    the trigger says then, not to what someone confirmed when the schedule was created. Two
    edits break that confirmation: a person-less trigger becoming `batch`, and a batch
    trigger's filters being widened. Both leave a recurring send whose recipient count nobody
    was shown, so the cadence stops until it is created again through the audience preview.

    Called wherever the LIVE trigger changes (direct save, graph edit, publish), never for
    draft writes, which don't change what the scheduler reads. Returns how many it paused.
    """
    if not trigger_has_audience(after.trigger):
        return 0
    if trigger_has_audience(before.trigger) and (before.trigger or {}).get("filters") == (after.trigger or {}).get(
        "filters"
    ):
        return 0
    return after.schedules.filter(status=HogFlowScheduleStatus.ACTIVE).update(
        status=HogFlowScheduleStatus.PAUSED, next_run_at=None, updated_at=timezone.now()
    )


def _apply_status_request(
    instance: HogFlow, locked: HogFlow, validated_data: dict, user_id: Optional[int]
) -> tuple[dict, tuple[WorkflowEvent, ...]]:
    """Route a requested status through the enable rule. Returns the fields left to save and the events."""
    requested = validated_data.get("status", locked.status)
    if requested == locked.status:
        return _go_live_after_waiting_edit(instance, locked, validated_data)
    if requested == HogFlowState.WAITING_FOR_DOMAIN:
        # Only the enable rule sets it. A client that sends it back read it before a change landed.
        raise WorkflowStale()
    if requested == HogFlowState.ACTIVE:
        return _apply_enable(instance, locked, validated_data, user_id)
    return validated_data, _events_on_leaving(locked)


def _go_live_after_waiting_edit(
    instance: HogFlow, locked: HogFlow, validated_data: dict
) -> tuple[dict, tuple[WorkflowEvent, ...]]:
    """An edit can drop or switch a waiting workflow's unverified sender, so check its senders again."""
    if locked.status != HogFlowState.WAITING_FOR_DOMAIN:
        return validated_data, ()
    if "actions" in validated_data:
        instance.actions = validated_data["actions"]
    change = _go_live_once_senders_verified(instance, activated_by="user")
    if change is None:
        return validated_data, ()
    return _without_status(validated_data), change.events


def update_workflow(
    *,
    team_id: int,
    user_id: Optional[int],
    hog_flow_id: UUID,
    validated_data: dict,
    route_to_draft: bool,
    base_updated_at: Optional[str],
    base_live_updated_at: Optional[str],
    includes_staged_draft: bool,
    validated_status: str,
) -> WorkflowWriteResult:
    # Optimistic concurrency: a client may send the `updated_at` it last loaded as `base_updated_at`.
    # If the stored row is strictly newer, another channel (a second UI tab, MCP, or the API) wrote in
    # between, so we reject with 409 rather than silently clobbering it. Strictly-newer (not equality)
    # avoids false positives from timestamp round-tripping - equal means the client is already current.
    # Callers that omit `base_updated_at` keep the previous last-writer-wins behavior.
    base_stamp = _parse_stamp(base_updated_at)

    with transaction.atomic():
        before_update = HogFlow.objects.select_for_update().get(pk=hog_flow_id, team_id=team_id)
        # Validation ran before this lock, and a draft validates leniently. If the status moved since
        # and the payload does not set it, that lenient content would land on a live workflow.
        if "status" not in validated_data and before_update.status != validated_status:
            raise WorkflowStale()
        # The write target is a second read, so `before_update` keeps the pre-write state.
        instance = HogFlow.objects.get(pk=hog_flow_id, team_id=team_id)
        events: tuple[WorkflowEvent, ...] = ()

        # Draft edits race against other draft edits, not against the live row (which they don't
        # touch), so the staleness baseline is the draft's own timestamp once a draft exists.
        guard_timestamp = before_update.updated_at
        if route_to_draft and before_update.draft_updated_at:
            guard_timestamp = before_update.draft_updated_at
        # The web builder sends "includes_staged_draft" (raw body, like "stage_draft") when a save on
        # a non-active workflow carries the staged draft merged into it. The draft is only cleared on
        # that explicit signal, so an API caller that resends live content never loses a draft.
        clears_staged_draft = (
            not route_to_draft
            and before_update.status != HogFlow.State.ACTIVE
            and before_update.draft is not None
            and includes_staged_draft
        )
        if clears_staged_draft:
            # A revision restore writes the draft without moving the live stamp, so fence on the newer one.
            if before_update.draft_updated_at and (
                guard_timestamp is None or before_update.draft_updated_at > guard_timestamp
            ):
                guard_timestamp = before_update.draft_updated_at
        if base_stamp and guard_timestamp and guard_timestamp > base_stamp:
            raise WorkflowStale()

        if route_to_draft:
            _write_draft(instance, before_update, validated_data)
            # Metadata in the same payload still applies live. Content (and the fields validate()
            # derives from it - trigger, billable_action_types) must not leak onto the live row:
            # they were computed from the draft's graph.
            remaining = {
                k: v
                for k, v in validated_data.items()
                if k not in DRAFT_CONTENT_FIELDS and k != "billable_action_types"
            }
            if remaining:
                # The draft-stamp guard above doesn't protect this live write: a concurrent
                # live-metadata edit bumps updated_at but not draft_updated_at, so a staged save
                # would silently overwrite it. Clients that write metadata alongside a staged
                # draft send the live stamp they loaded as a second fence.
                base_live = _parse_stamp(base_live_updated_at)
                if base_live and before_update.updated_at and before_update.updated_at > base_live:
                    raise WorkflowStale()
                _save_live(instance, remaining)
        else:
            validated_data = _derive_from_locked_graph(before_update, validated_data)
            validated_data, events = _apply_status_request(instance, before_update, validated_data, user_id)
            _refresh_action_redirects(instance, before_update, validated_data.get("actions"))
            bump = _stage_revision_bump(instance, before_update, validated_data)
            if clears_staged_draft:
                _save_live(instance, validated_data, draft=None, draft_updated_at=None, draft_encrypted_inputs=None)
                unstage_workflow_proposals(team_id=instance.team_id, hog_flow_id=instance.pk)
            else:
                _save_live(instance, validated_data)
            if bump:
                _append_revisions(team_id, user_id, instance, before_update)

    paused = 0
    if not route_to_draft:
        _reschedule_timing_edits(team_id, before_update, instance)
        paused = _pause_schedules_on_audience_change(before_update, instance)
    return WorkflowWriteResult(
        previous=field_values(before_update),
        current=field_values(instance),
        schedules_paused=paused,
        events=events,
    )


def edit_workflow_content(
    *,
    team_id: int,
    user_id: Optional[int],
    hog_flow_id: UUID,
    stage_if_active: bool,
    base_updated_at: Optional[str],
    edit: Callable[[WorkflowEditState, list[dict], list[dict]], dict],
    changes_graph: bool,
) -> WorkflowWriteResult:
    """Apply a surgical edit under the row lock. `edit` receives the locked workflow, and the actions and
    edges it builds on (the staged draft's when the edit stages), and returns the validated fields to write."""
    with transaction.atomic():
        locked = HogFlow.objects.select_for_update().get(pk=hog_flow_id, team_id=team_id)

        route_to_draft = stage_if_active and locked.status == HogFlow.State.ACTIVE

        # Optimistic concurrency, mirroring update_workflow: the surgical endpoints are the only MCP
        # paths that write graph content, so they carry the base_updated_at staleness contract.
        # Draft edits race against other draft edits, so the baseline is the draft's timestamp
        # once one exists.
        base_stamp = _parse_stamp(base_updated_at)
        guard_timestamp = locked.updated_at
        if route_to_draft and locked.draft_updated_at:
            guard_timestamp = locked.draft_updated_at
        if base_stamp and guard_timestamp and guard_timestamp > base_stamp:
            raise WorkflowStale()

        # Draft edits compose on the staged draft, not on live - a second patch must see the first.
        if route_to_draft and locked.draft:
            base_actions = list(locked.draft.get("actions") or [])
            base_edges = list(locked.draft.get("edges") or [])
        else:
            base_actions = list(locked.actions or [])
            base_edges = list(locked.edges or [])

        validated_data = edit(to_edit_state(locked), base_actions, base_edges)

        before_update = HogFlow.objects.get(pk=hog_flow_id, team_id=team_id)
        events: tuple[WorkflowEvent, ...] = ()
        if route_to_draft:
            _write_draft(locked, locked, validated_data)
        else:
            validated_data, events = _go_live_after_waiting_edit(locked, before_update, validated_data)
            # An email edit can't delete steps or change timing config, so only graph edits refresh redirects.
            if changes_graph:
                _refresh_action_redirects(locked, before_update, validated_data.get("actions"))
            bump = _stage_revision_bump(locked, before_update, validated_data)
            _save_live(locked, validated_data)
            if bump:
                _append_revisions(team_id, user_id, locked, before_update)

    paused = 0
    went_live = locked.status != before_update.status
    if (changes_graph or went_live) and not route_to_draft:
        _reschedule_timing_edits(team_id, before_update, locked)
        paused = _pause_schedules_on_audience_change(before_update, locked)
    return WorkflowWriteResult(
        previous=field_values(before_update),
        current=field_values(locked),
        routed_to_draft=route_to_draft,
        schedules_paused=paused,
        events=events,
    )


def publish_draft(
    *,
    team_id: int,
    user_id: Optional[int],
    hog_flow_id: UUID,
    previewed_value: str,
    validate: Callable[[WorkflowEditState, dict], dict],
) -> WorkflowWriteResult:
    """Promote the staged draft to the live config. `validate` receives the locked workflow and the draft
    content, and returns the validated fields to write."""
    with transaction.atomic():
        locked = HogFlow.objects.select_for_update().get(pk=hog_flow_id, team_id=team_id)
        if not locked.draft:
            raise WorkflowHasNoDraft()
        if previewed_value != publish_confirm_value(hog_flow_id=locked.id, draft_updated_at=locked.draft_updated_at):
            raise WorkflowStale()

        before_update = HogFlow.objects.get(pk=hog_flow_id, team_id=team_id)
        # The draft goes back through the normal serializer so publish revalidates strictly and
        # recompiles bytecode - a stored blob is never trusted to be execution-ready.
        validated_data = validate(to_edit_state(locked), dict(locked.draft))
        validated_data, events = _go_live_after_waiting_edit(locked, before_update, validated_data)
        _refresh_action_redirects(locked, before_update, validated_data.get("actions"))
        bump = _stage_revision_bump(locked, before_update, validated_data)
        # Validation recovered the draft's secrets (from the merged live+draft encrypted maps), and
        # the save re-splits them into the live encrypted_inputs column. The draft's own secret
        # column is then cleared alongside the draft.
        _save_live(locked, validated_data)
        if bump:
            _append_revisions(team_id, user_id, locked, before_update)
        locked.draft = None
        locked.draft_updated_at = None
        locked.draft_encrypted_inputs = None
        locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])
        apply_approved_proposals_for_flow(locked)

    _reschedule_timing_edits(team_id, before_update, locked)
    paused = _pause_schedules_on_audience_change(before_update, locked)
    return WorkflowWriteResult(
        previous=field_values(before_update), current=field_values(locked), schedules_paused=paused, events=events
    )


def discard_draft(*, team_id: int, hog_flow_id: UUID) -> WorkflowWriteResult:
    """Throw away the staged draft. Idempotent: discarding when nothing is staged is a no-op."""
    with transaction.atomic():
        locked = HogFlow.objects.select_for_update().get(pk=hog_flow_id, team_id=team_id)
        before_update = HogFlow.objects.get(pk=hog_flow_id, team_id=team_id)
        locked.draft = None
        locked.draft_updated_at = None
        locked.draft_encrypted_inputs = None
        # updated_at (auto_now) is deliberately bumped: without a fresh live stamp the
        # resource_edited broadcast carries the old updated_at - older than the draft stamp
        # concurrent editors loaded, so they'd ignore the discard, and their next draft save
        # would pass the staleness guard (which falls back to the live stamp once the draft is
        # gone) and silently resurrect the discarded draft.
        locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs", "updated_at"])
        unstage_workflow_proposals(team_id=locked.team_id, hog_flow_id=locked.pk)
    return WorkflowWriteResult(previous=field_values(before_update), current=field_values(locked))
