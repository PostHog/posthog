"""Push admission: the checks, the reservation of adopted entities, the lease, and dispatch to the worker."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.utils import uuid7

from .. import engine_adapter
from ..db import WRITER_DB
from ..facade.contracts import StartPushInput
from ..facade.enums import BindingOrigin, BindingStatus, DiffStatus, PushStatus, StackErrorKind
from ..models import Stack, StackDiff
from ..temporal import client as temporal_client
from . import grants, lease, managed, records
from .stacks import (
    _error,
    bound_kinds,
    check_organization_kinds,
    claimed_message,
    get_diff_for_update,
    get_stack,
    runner_unavailable_error,
    stack_moved_error,
)

logger = structlog.get_logger(__name__)


def removal_count(diff: dict | None) -> int:
    """Entities a push would destroy: removals, and recreates, which delete the original and its history. A
    release deletes nothing, so it does not count."""
    summary = (diff or {}).get("summary", {})
    return int(summary.get("remove", 0)) + int(summary.get("recreate", 0))


def _check_pushable(stack: Stack, diff: StackDiff, max_removals: int | None, now: datetime) -> None:
    if diff.status == DiffStatus.STALE.value:
        raise stack_moved_error()
    if diff.status == DiffStatus.PUSHED.value:
        raise _error(StackErrorKind.CONFLICT, "diff_pushed", "This diff was already pushed. Run diff again.")
    if diff.status != DiffStatus.READY.value or diff.encrypted_saved_diff is None:
        raise _error(
            StackErrorKind.CONFLICT,
            "diff_not_ready",
            "This diff is not ready to push. Wait for it to finish, or run diff again if it failed.",
        )
    if diff.expires_at <= now:
        raise _error(StackErrorKind.CONFLICT, "diff_expired", "This diff expired. Run diff again.")
    if stack.needs_reconcile:
        raise _error(
            StackErrorKind.CONFLICT,
            "push_uncertain",
            "The last push stopped before it reported what it changed. Run diff again, review its warnings, adopt "
            f"what the push already made, then reconcile with `POST stacks/{stack.name}/reconcile/` and push.",
        )
    if (diff.base_serial, diff.base_revision, diff.base_secret_revision) != (
        stack.serial,
        stack.revision,
        stack.secret_revision,
    ):
        records.stale_ready_diffs(stack)
        raise stack_moved_error()
    removals = removal_count(diff.diff)
    cap = stack.max_removals if max_removals is None else max_removals
    if removals > cap:
        raise _error(
            StackErrorKind.INVALID,
            "too_many_removals",
            f"This push removes or recreates {removals} entities, and this stack allows {cap} per push. "
            f"Check the diff, then push again with max_removals set to {removals} to confirm.",
        )


def _reserve_natural_identities(stack: Stack, diff: StackDiff) -> None:
    """Take every natural identity this push creates or adopts, so a second stack that plans the same key is
    refused here instead of reaching the API."""
    natural = engine_adapter.natural_key_kinds()
    for change in diff.planned or []:
        if change["action"] not in ("create", "adopt", "recreate") or change["kind"] not in natural:
            continue
        records.reserve_natural(stack, change["kind"], change["key"])


def _reserve_adoptions(stack: Stack, diff: StackDiff, description: dict) -> None:
    """Record every entity this push adopts as pending for the stack, so a second stack cannot adopt it too.

    Reads the private plan, never the redacted public diff, so redaction cannot change what is reserved.
    """
    sources = records.sources_by_identity(description)
    for change in diff.planned or []:
        if change["action"] != "adopt" or not change.get("entity_id"):
            continue
        kind, key, entity_id = str(change["kind"]), str(change["key"]), str(change["entity_id"])
        source_file, source_export = sources.get((kind, key), ("", ""))
        existing = records.bindings(stack.team_id).filter(stack_id=stack.id, kind=kind, key=key).first()
        if existing is not None and existing.status == BindingStatus.BOUND.value:
            continue
        try:
            with transaction.atomic(using=WRITER_DB):
                if existing is None:
                    records.bindings(stack.team_id).create(
                        team_id=stack.team_id,
                        stack=stack,
                        kind=kind,
                        key=key,
                        entity_id=entity_id,
                        status=BindingStatus.PENDING.value,
                        origin=BindingOrigin.ADOPTED.value,
                        claim_scope=records.claim_scope(stack, kind),
                        source_file=source_file,
                        source_export=source_export,
                    )
                else:
                    records.bindings(stack.team_id).filter(id=existing.id).update(
                        entity_id=entity_id, status=BindingStatus.PENDING.value, origin=BindingOrigin.ADOPTED.value
                    )
        except IntegrityError:
            claim = (
                records.managed_in_scope([records.claim_scope(stack, kind)])
                .filter(kind=kind, entity_id=entity_id)
                .exclude(stack_id=stack.id)
                .select_related("stack")
                .first()
            )
            raise _error(
                StackErrorKind.CONFLICT,
                "claimed_by_other_stack",
                claimed_message(claim) if claim else f"Another stack manages the {kind} {key}. Detach it there first.",
            )


def start_push(params: StartPushInput, scopes: list[str]) -> StackDiff:
    if params.caller.impersonated:
        raise _error(
            StackErrorKind.FORBIDDEN,
            "impersonated_push",
            "A push cannot run from an impersonated session. Ask the person to push, or push from your own account.",
        )
    stack = get_stack(params.team_id, params.stack_name)
    lease.recover_if_expired(stack)
    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        lease.check_unlocked(stack)
        diff = get_diff_for_update(stack, params.diff_id)
        if diff.target_team_id != params.caller.target_team_id:
            raise _error(StackErrorKind.NOT_FOUND, "diff_not_found", "No diff with this id exists for this project.")
        _check_pushable(stack, diff, params.max_removals, now)
        check_organization_kinds(stack, set(diff.kinds) | bound_kinds(stack))
        _reserve_natural_identities(stack, diff)
        _reserve_adoptions(stack, diff, records.description_of(diff))
        managed.forget_team(stack.team_id)
        attempt_id = uuid7()
        generation = stack.lease_generation + 1
        records.stacks(stack.team_id).filter(id=stack.id).update(
            lease_attempt_id=attempt_id, lease_generation=generation, lease_expires_at=now + lease.ADMISSION_LEASE
        )
        records.diffs(stack.team_id).filter(id=diff.id).update(
            push_attempt_id=attempt_id,
            push_generation=generation,
            push_status=PushStatus.RUNNING.value,
            pushed_by_id=params.caller.user_id,
            pushed_by_grant=grants.grant_dict(params.caller.grant),
            push_scopes=scopes,
            push_token_id=None,
            push_errors=[],
            push_started_at=now,
            push_finished_at=None,
        )
        team_id, diff_id = stack.team_id, diff.id
        transaction.on_commit(lambda: _dispatch_push(team_id, diff_id, attempt_id), using=WRITER_DB)
    return records.diffs(stack.team_id).select_related("stack").get(id=diff.id)


def _dispatch_push(team_id: int, diff_id: UUID, attempt_id: UUID) -> None:
    try:
        temporal_client.start_push_workflow(team_id=team_id, diff_id=diff_id, attempt_id=attempt_id)
    except WorkflowAlreadyStartedError:
        # The attempt's workflow exists, so it is running or ran. Its own worker reports the outcome.
        return
    except Exception:
        # Temporal may have started the workflow before the error reached us, so a worker may run it. The attempt
        # closes as uncertain: the stack waits for a reconcile rather than risk two workers.
        logger.exception("stacks_push_dispatch_failed", diff_id=str(diff_id))
        stack = records.diffs(team_id).select_related("stack").get(id=diff_id).stack
        lease.close_attempt(stack, attempt_id, [runner_unavailable_error()], status=PushStatus.UNCERTAIN)
