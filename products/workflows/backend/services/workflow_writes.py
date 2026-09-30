from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional, Protocol

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.team.team import Team
from posthog.models.user import User

from products.notifications.backend.facade.api import publish_resource_edited
from products.workflows.backend.facade.contracts import StaleWorkflowWrite, WorkflowUpdate
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.models.workflow_proposal import WorkflowProposal
from products.workflows.backend.presentation.views.action_redirects import compute_action_redirects
from products.workflows.backend.presentation.views.hog_flow import (
    DRAFT_CONTENT_FIELDS,
    TemplateCache,
    _trigger_has_audience,
    snapshot_flow_content,
    strip_content_secrets,
    strip_secrets_from_content,
    unstage_workflow_proposals,
)
from products.workflows.backend.services.timing_reschedule import (
    get_all_timing_action_ids,
    get_timing_reschedule_action_ids,
)
from products.workflows.backend.tasks.hog_flows import reschedule_hog_flow_timing

logger = structlog.get_logger(__name__)

WorkflowUsageReporter = Callable[[str, HogFlow, Optional[dict]], None]

_CLEARED_DRAFT: dict[str, Any] = {"draft": None, "draft_updated_at": None, "draft_encrypted_inputs": None}


class ValidatedWorkflow(Protocol):
    """A validated workflow payload that knows how to persist itself, such as a bound `HogFlowSerializer`."""

    # A property on DRF serializers, but it returns the live dict, so writers may narrow it in place before save().
    @property
    def validated_data(self) -> dict[str, Any]: ...

    def save(self, **kwargs: Any) -> HogFlow: ...


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


def _parse_client_timestamp(raw: Optional[str]) -> Optional[datetime]:
    parsed = parse_datetime(raw) if raw else None
    # A timezone-less timestamp parses naive; comparing it to the tz-aware stored updated_at would
    # raise TypeError (500). Assume UTC so callers can send a bare ISO string.
    if parsed is not None and timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def _staleness_baseline(row: HogFlow, *, stage_as_draft: bool) -> Optional[datetime]:
    # Draft edits race against other draft edits, not against the live row (which they don't
    # touch), so the staleness baseline is the draft's own timestamp once a draft exists.
    if stage_as_draft and row.draft_updated_at:
        return row.draft_updated_at
    return row.updated_at


def _reject_if_newer(baseline: Optional[datetime], loaded_at: Optional[datetime]) -> None:
    if loaded_at and baseline and baseline > loaded_at:
        raise StaleWorkflowWrite()


@frozen
class WorkflowWriter:
    """The save path for workflows: every write that changes a workflow's live content or its staged
    draft, with the revision history, action redirects, activity log and edit broadcast that go with it.
    Callers validate the payload first and hand over the result."""

    team: Team
    user: Optional[User]
    was_impersonated: bool
    report_usage: WorkflowUsageReporter

    def create(self, validated: ValidatedWorkflow) -> HogFlow:
        workflow = validated.save(created_by=self.user, team_id=self.team.id)
        self._log_activity(workflow, "created", detail_type="standard")
        self.announce_edited(workflow)
        return workflow

    def update(self, instance: HogFlow, validated: ValidatedWorkflow, options: WorkflowUpdate) -> Optional[HogFlow]:
        """Apply an update to `instance` and return the workflow as it was before the write."""
        # Optimistic concurrency: a client may send the `updated_at` it last loaded as `base_updated_at`.
        # If the stored row is strictly newer, another channel (a second UI tab, MCP, or the API) wrote in
        # between, so we reject with 409 rather than silently clobbering it. Strictly-newer (not equality)
        # avoids false positives from timestamp round-tripping — equal means the client is already current.
        # Callers that omit `base_updated_at` keep the previous last-writer-wins behavior.
        base_updated_at = _parse_client_timestamp(options.base_updated_at)

        with transaction.atomic():
            try:
                # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance; locked for the staleness check + save)
                before_update = HogFlow.objects.select_for_update().get(pk=instance.id)
            except HogFlow.DoesNotExist:
                before_update = None

            guard_timestamp = (
                _staleness_baseline(before_update, stage_as_draft=options.stage_as_draft) if before_update else None
            )
            # The draft is only cleared on the caller's explicit signal, so an API caller that resends live
            # content never loses a draft.
            clears_staged_draft = (
                not options.stage_as_draft
                and before_update is not None
                and before_update.status != HogFlow.State.ACTIVE
                and before_update.draft is not None
                and options.replaces_staged_draft
            )
            if clears_staged_draft:
                assert before_update is not None
                # A revision restore writes the draft without moving the live stamp, so fence on the newer one.
                if before_update.draft_updated_at and (
                    guard_timestamp is None or before_update.draft_updated_at > guard_timestamp
                ):
                    guard_timestamp = before_update.draft_updated_at
            _reject_if_newer(guard_timestamp, base_updated_at)

            if options.stage_as_draft:
                assert before_update is not None
                self._stage_update(instance, before_update, validated, options)
            else:
                self.write_live(instance, before_update, validated, **(_CLEARED_DRAFT if clears_staged_draft else {}))
                if clears_staged_draft:
                    unstage_workflow_proposals(instance)

        if not options.stage_as_draft:
            self.after_live_write(before_update, instance)
        self._log_activity(instance, "updated", previous=before_update)
        self.announce_edited(instance)
        return before_update

    def publish_draft(self, instance: HogFlow, validate_draft: Callable[[HogFlow], ValidatedWorkflow]) -> HogFlow:
        """Promote the staged draft to the live config. `validate_draft` receives the locked row, checks it
        is still the draft the caller confirmed, and validates the draft content."""
        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = HogFlow.objects.select_for_update().get(pk=instance.pk)
            validated = validate_draft(locked)
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFlow.objects.get(pk=instance.pk)
            # save() runs update(), which recovers the draft's secrets (from the merged live+draft
            # encrypted maps) and re-splits them into the live encrypted_inputs column. The draft's own
            # secret column is then cleared alongside the draft.
            self.write_live(locked, before_update, validated)
            locked.draft = None
            locked.draft_updated_at = None
            locked.draft_encrypted_inputs = None
            locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])
            # Every path that changes the draft unstages what it dropped, so whatever is approved here just went live.
            WorkflowProposal.objects.filter(hog_flow=locked, status=WorkflowProposal.Status.APPROVED).update(
                status=WorkflowProposal.Status.APPLIED, applied_version=locked.version
            )

        self.after_live_write(before_update, locked)
        self._log_activity(locked, "published", previous=before_update)
        self.announce_edited(locked)
        return locked

    def check_fresh(self, locked: HogFlow, base_updated_at: Optional[str], *, stage_as_draft: bool) -> None:
        """Raise `StaleWorkflowWrite` when `locked` changed after the client loaded it at `base_updated_at`."""
        _reject_if_newer(
            _staleness_baseline(locked, stage_as_draft=stage_as_draft), _parse_client_timestamp(base_updated_at)
        )

    def write_live(
        self, target: HogFlow, before: Optional[HogFlow], validated: ValidatedWorkflow, **fields: Any
    ) -> None:
        """Save validated content onto the live row, with its action redirects and revision. Runs inside
        the caller's transaction, with `target` locked and `before` read as it was before this write."""
        bump = False
        if before is not None:
            self._refresh_action_redirects(target, before, validated.validated_data.get("actions"))
            bump = self.stage_revision_bump(target, before, validated.validated_data)
        validated.save(**fields)
        if bump:
            assert before is not None
            self.append_revisions(target, before)

    def write_draft(self, instance: HogFlow, locked: HogFlow, validated: ValidatedWorkflow) -> None:
        """Stage validated content as the draft. Runs inside the caller's transaction, with `locked` locked."""
        validated_data = validated.validated_data
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
        unstage_workflow_proposals(instance)

    def stage_revision_bump(self, instance: HogFlow, before: HogFlow, validated_data: dict) -> bool:
        """Set the next version on `instance` when the content changed. Call it inside the locked write transaction."""
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
        # recovered into `actions` (stripping happens later in save()), while `before` is the persisted
        # stripped snapshot; without this a secret-bearing flow would bump on every actions-carrying save.
        template_cache: TemplateCache = {}
        old_content = _without_bytecode_contracts(strip_content_secrets(raw_old, template_cache))
        new_content = _without_bytecode_contracts(strip_content_secrets(raw_new, template_cache))
        if new_content == old_content:
            return False
        instance.version = (before.version or 0) + 1
        return True

    def append_revisions(self, instance: HogFlow, before: HogFlow) -> None:
        # Must run inside the same transaction as the content write it snapshots. On the first
        # tracked write, also snapshot the outgoing live content so the state before any tracked
        # change is always available to roll back to (there's no backfill).
        if not HogFlowRevision.objects.filter(hog_flow=instance).exists():
            HogFlowRevision.objects.create(
                team_id=self.team.id,
                hog_flow=instance,
                version=before.version,
                content=snapshot_flow_content(before),
                created_by=None,
            )
        HogFlowRevision.objects.create(
            team_id=self.team.id,
            hog_flow=instance,
            version=instance.version,
            content=snapshot_flow_content(instance),
            created_by=self.user,
        )

    def after_live_write(self, before: Optional[HogFlow], after: HogFlow) -> None:
        """Follow-up work for a change to the live config: never for draft writes, which don't touch what
        runs execute or what the scheduler reads."""
        self._reschedule_timing_edits(before, after)
        self._pause_schedules_on_audience_change(before, after)

    def announce_edited(self, workflow: HogFlow) -> None:
        # Realtime "edited elsewhere" signal so an open builder (or another tab) can refresh instead of
        # clobbering edits made via a different channel (UI/MCP/API). Fires for every channel; the
        # frontend dedupes its own echo by comparing updated_at. Transient — no inbox notification.
        # Draft writes don't touch the live updated_at, so broadcast the newer of the two stamps;
        # otherwise an open builder never hears about content staged from another channel.
        edited_at = workflow.updated_at
        if workflow.draft_updated_at and workflow.draft_updated_at > edited_at:
            edited_at = workflow.draft_updated_at
        publish_resource_edited(
            team=self.team,
            resource_type="HogFlow",
            resource_id=str(workflow.id),
            updated_at=edited_at.isoformat(),
            actor_user_id=self.user.id if self.user else None,
            ac_resource_type="hog_flow",
        )

    def _stage_update(
        self, instance: HogFlow, locked: HogFlow, validated: ValidatedWorkflow, options: WorkflowUpdate
    ) -> None:
        self.write_draft(instance, locked, validated)
        # Metadata in the same payload still applies live. Content (and the fields validate()
        # derives from it — trigger, billable_action_types) must not leak onto the live row:
        # they were computed from the draft's graph.
        remaining = {
            k: v
            for k, v in validated.validated_data.items()
            if k not in DRAFT_CONTENT_FIELDS and k != "billable_action_types"
        }
        if not remaining:
            return
        # The draft-stamp guard above doesn't protect this live write: a concurrent
        # live-metadata edit bumps updated_at but not draft_updated_at, so a staged save
        # would silently overwrite it. Clients that write metadata alongside a staged
        # draft send the live stamp they loaded as a second fence.
        base_live = _parse_client_timestamp(options.base_live_updated_at)
        if base_live and locked.updated_at and locked.updated_at > base_live:
            raise StaleWorkflowWrite()
        validated.validated_data.clear()
        validated.validated_data.update(remaining)
        validated.save()

    def _refresh_action_redirects(self, target: HogFlow, old: HogFlow, new_actions: Optional[list]) -> None:
        # Skip-forward for deleted steps: refresh the redirect map whenever a live graph write is about
        # to land, while both the old graph (`old`, the locked pre-write row) and the new actions are in
        # hand. Must run before serializer.save() so the map persists in the same write, transaction,
        # and worker reload as the graph it describes.
        # No status gate: disabling a flow doesn't purge its parked runs (the worker only cancels them
        # if they wake while the flow is still disabled), so a step deleted during a disable/re-enable
        # window needs its redirect recorded just like one deleted live.
        if new_actions is None:
            return
        target.action_redirects = compute_action_redirects(
            old.actions or [], old.edges or [], new_actions, old.action_redirects
        )

    def _reschedule_timing_edits(self, before: Optional[HogFlow], after: HogFlow) -> None:
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
        if not before or after.status != HogFlow.State.ACTIVE:
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
        team_id = self.team.id
        hog_flow_id = str(after.id)
        transaction.on_commit(
            lambda: reschedule_hog_flow_timing.delay(team_id=team_id, hog_flow_id=hog_flow_id, action_ids=action_ids)
        )

    def _pause_schedules_on_audience_change(self, before: Optional[HogFlow], after: HogFlow) -> None:
        """Pause every active schedule when the audience a batch dispatch fans out to changes.

        The scheduler reads the live trigger at fire time, so each firing broadcasts to whatever
        the trigger says then, not to what someone confirmed when the schedule was created. Two
        edits break that confirmation: a person-less trigger becoming `batch`, and a batch
        trigger's filters being widened. Both leave a recurring send whose recipient count nobody
        was shown, so the cadence stops until it is created again through the audience preview.

        Called wherever the LIVE trigger changes (direct save, graph edit, publish), never for
        draft writes, which don't change what the scheduler reads.
        """
        if not before or not _trigger_has_audience(after):
            return
        if _trigger_has_audience(before) and (before.trigger or {}).get("filters") == (after.trigger or {}).get(
            "filters"
        ):
            return
        paused = after.schedules.filter(status=HogFlowSchedule.Status.ACTIVE).update(
            status=HogFlowSchedule.Status.PAUSED, next_run_at=None, updated_at=timezone.now()
        )
        if paused:
            self.report_usage("hog_flow_schedules_paused_on_audience_change", after, {"paused": paused})

    def _log_activity(
        self,
        workflow: HogFlow,
        activity: str,
        *,
        previous: Optional[HogFlow] = None,
        detail_type: Optional[str] = None,
    ) -> None:
        # The audit trail must never fail a write that already committed.
        try:
            log_activity(
                organization_id=self.team.organization_id,
                team_id=self.team.id,
                user=self.user,
                was_impersonated=self.was_impersonated,
                item_id=str(workflow.id),
                scope="HogFlow",
                activity=activity,
                detail=Detail(
                    name=workflow.name or "HogFlow",
                    type=detail_type,
                    changes=changes_between("HogFlow", previous=previous, current=workflow)
                    if previous is not None
                    else None,
                ),
            )
        except Exception:
            logger.exception("workflows.activity_log_failed", workflow_id=str(workflow.id), activity=activity)
