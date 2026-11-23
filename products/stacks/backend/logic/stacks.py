"""Stacks, diff admission, bindings and secrets: the requests a caller makes, before any engine work runs."""

from __future__ import annotations

import re
import json
import hashlib
from datetime import timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from .. import engine_adapter
from ..db import WRITER_DB, database_ready
from ..facade.contracts import AdoptInput, Caller, DiffSource, SetSecretInput, StackServiceError, StartDiffInput
from ..facade.enums import BindingOrigin, BindingStatus, DiffStatus, StackErrorKind
from ..models import Stack, StackBinding, StackDiff, StackSecret
from ..temporal import client as temporal_client
from . import crypto, grants, kinds, lease, records, secrets, validation

logger = structlog.get_logger(__name__)

STACK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# These names are routes under /stacks/ of their own.
RESERVED_STACK_NAMES = frozenset({"bindings", "adoptable", "managed_kinds", "modules"})
# A saved diff can hold secret values, so it is pushable for a bounded time only.
DIFF_LIFETIME = timedelta(hours=24)
# Longer than the engine's own run timeout plus the wait in the queue. A diff still running then is closed.
DIFF_DEADLINE = timedelta(minutes=45)
SUMMARY_ACTIONS = ("create", "update", "recreate", "remove", "adopt", "rename", "release")


def _error(kind: StackErrorKind, code: str, message: str) -> StackServiceError:
    return StackServiceError(kind, code, message)


def ensure_ready() -> None:
    """Refuse work this instance cannot store safely: no product database, or no encryption key."""
    if not database_ready() or not crypto.keys_ready():
        raise _error(
            StackErrorKind.UNAVAILABLE,
            "stacks_unavailable",
            "Stacks are not set up on this PostHog instance yet. Contact support.",
        )


def stack_moved_error() -> StackServiceError:
    return _error(
        StackErrorKind.CONFLICT,
        "stack_moved",
        "The stack changed since this diff was made. Run diff again and push the new diff.",
    )


def runner_unavailable_error() -> dict:
    return {"code": "runner_unavailable", "message": "PostHog could not start this run. Try again in a few minutes."}


def description_hash(description: dict) -> str:
    canonical = json.dumps(description, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def description_kinds(description: dict) -> set[str]:
    return {str(resource.get("kind")) for resource in description.get("resources", [])}


def validate_stack_name(name: str) -> None:
    if len(name) > 100 or not STACK_NAME.fullmatch(name) or name in RESERVED_STACK_NAMES:
        raise _error(
            StackErrorKind.INVALID,
            "invalid_stack_name",
            "Use a stack name of lowercase letters, digits, dashes and underscores, at most 100 characters, "
            "other than 'bindings', 'adoptable', 'managed_kinds' and 'modules'.",
        )


def _stacks_of(target_team_id: int) -> QuerySet[Stack]:
    """Stacks of exactly this project. `team_id` is the canonical parent, shared by every environment."""
    return records.stacks(resolve_effective_team_id(target_team_id)).filter(target_team_id=target_team_id)


def get_stack(team_id: int, name: str) -> Stack:
    """The stack named `name` in exactly the project `team_id`, the one the route resolved."""
    stack = _stacks_of(team_id).filter(name=name).first()
    if stack is None:
        raise _error(StackErrorKind.NOT_FOUND, "stack_not_found", f"No stack named {name} exists in this project.")
    return stack


def get_or_create_stack(team_id: int, name: str, caller: Caller) -> Stack:
    validate_stack_name(name)
    stack = _stacks_of(team_id).filter(name=name).first()
    if stack is not None:
        return stack
    canonical = resolve_effective_team_id(team_id)
    try:
        with transaction.atomic(using=WRITER_DB):
            return records.stacks(canonical).create(
                team_id=canonical,
                target_team_id=team_id,
                name=name,
                created_by_id=caller.user_id,
                organization_id=caller.organization_id,
            )
    except IntegrityError:
        # Two first requests for one stack can race. The loser reads the winner's row.
        return get_stack(team_id, name)


def _public_diffs(team_id: int) -> QuerySet[StackDiff]:
    # Polling reads only what the response shows, never the encrypted description or saved diff.
    return (
        records.diffs(team_id)
        .select_related("stack")
        .only(
            "id",
            "team_id",
            "target_team_id",
            "stack",
            "stack__name",
            "stack__team_id",
            "kinds",
            "status",
            "diff",
            "run_scopes",
            "created_by_id",
            "source_repository",
            "source_branch",
            "source_commit",
            "created_at",
            "expires_at",
            "push_status",
            "push_errors",
        )
    )


def get_diff(team_id: int, stack_name: str, diff_id: UUID, *, target_team_id: int) -> StackDiff:
    diff = (
        _public_diffs(resolve_effective_team_id(team_id))
        .filter(id=diff_id, stack__name=stack_name, stack__target_team_id=team_id, target_team_id=target_team_id)
        .first()
    )
    if diff is None:
        raise _error(StackErrorKind.NOT_FOUND, "diff_not_found", "No diff with this id exists for this stack.")
    return diff


def get_diff_for_update(stack: Stack, diff_id: UUID) -> StackDiff:
    diff = records.diffs(stack.team_id).select_for_update().filter(id=diff_id, stack_id=stack.id).first()
    if diff is None:
        raise _error(StackErrorKind.NOT_FOUND, "diff_not_found", "No diff with this id exists for this stack.")
    diff.stack = stack
    return diff


def bound_kinds(stack: Stack) -> set[str]:
    return set(records.bindings(stack.team_id).filter(stack_id=stack.id).values_list("kind", flat=True))


def diff_scopes(team_id: int, stack_name: str, description: dict, *, write: bool) -> list[str]:
    """The scopes a run of this description needs: its kinds, and the kinds the stack already holds, because
    removing the last definition of a kind still reads and removes that kind's entities."""
    stack = _stacks_of(team_id).filter(name=stack_name).first()
    held = bound_kinds(stack) if stack is not None else set()
    return kinds.run_scopes(description_kinds(description) | held, write=write)


def push_scopes(team_id: int, stack_name: str, diff_id: UUID, *, target_team_id: int) -> list[str]:
    diff = get_diff(team_id, stack_name, diff_id, target_team_id=target_team_id)
    return kinds.run_scopes(set(diff.kinds) | bound_kinds(diff.stack), write=True)


def claimed_message(claim: StackBinding) -> str:
    where = f" from {claim.stack.repository}" if claim.stack.repository else ""
    return (
        f"The {claim.kind} {claim.key} is managed by the stack {claim.stack.name}{where}. "
        f"Remove it from one of the two stacks, or detach it in {claim.stack.name} first."
    )


def claimed_keys_error(stack: Stack, description: dict) -> dict | None:
    """The diff error for a natural key another stack already manages, or None.

    For a kind with a natural key, such as a flag key or an event name, the key is the entity, so two
    stacks with one key would both manage one entity.
    """
    natural = engine_adapter.natural_key_kinds()
    keys = {(r["kind"], r["key"]) for r in description.get("resources", []) if r["kind"] in natural}
    if not keys:
        return None
    candidates = (
        records.managed_in_scope(records.claim_scope(stack, kind) for kind, _ in keys)
        .filter(kind__in=sorted({kind for kind, _ in keys}), key__in=sorted({key for _, key in keys}))
        .exclude(stack_id=stack.id)
        .select_related("stack")
        .order_by("kind", "key")
    )
    claim = next((row for row in candidates if (row.kind, row.key) in keys), None)
    if claim is None:
        return None
    return {"code": "claimed_by_other_stack", "message": claimed_message(claim), "kind": claim.kind, "key": claim.key}


def check_organization_kinds(stack: Stack, kinds_used: set[str]) -> None:
    """A kind every project of the organization shares, such as a context page, needs the stack's opt-in."""
    shared = sorted(kind for kind in kinds_used if engine_adapter.ownership_scope(kind) == "organization")
    if shared and not stack.context_pages_enabled:
        raise _error(
            StackErrorKind.INVALID,
            "context_pages_not_enabled",
            f"This stack defines {', '.join(shared)}, which every project of the organization shares. An "
            "organization admin turns on context pages for this stack first, with "
            f"`POST stacks/{stack.name}/context_pages/`.",
        )


def set_context_pages(team_id: int, stack_name: str, *, enabled: bool, caller: Caller) -> Stack:
    if not caller.is_organization_admin:
        raise _error(
            StackErrorKind.FORBIDDEN,
            "organization_admin_required",
            "Only an organization admin can let a stack manage context pages, because they belong to the whole "
            "organization.",
        )
    stack = get_or_create_stack(team_id, stack_name, caller)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        if stack.context_pages_enabled != enabled:
            records.stacks(stack.team_id).filter(id=stack.id).update(context_pages_enabled=enabled)
            stack.context_pages_enabled = enabled
            if not enabled:
                # A ready diff or a queued push may touch context pages. Neither stays pushable, and a queued push
                # checks the setting again before it mints its token.
                records.advance_revision(stack)
    return stack


def empty_diff(errors: list[dict]) -> dict:
    return {"changes": [], "drift": [], "summary": dict.fromkeys(SUMMARY_ACTIONS, 0), "errors": errors}


def start_diff(params: StartDiffInput, scopes: list[str]) -> StackDiff:
    ensure_ready()
    validation.check_limits(params.description)
    stack = get_or_create_stack(params.team_id, params.stack_name, params.caller)
    check_organization_kinds(stack, description_kinds(params.description))
    # Nothing about the description is stored before the engine's checks pass, because a literal credential in a
    # secret-bearing field would otherwise reach the database.
    validation.check_description(params.description, engine_bindings(stack))
    missing = secrets.missing_secrets(stack, secrets.secret_names(params.description))
    refusal = secrets.missing_secrets_error(missing) if missing else claimed_keys_error(stack, params.description)
    now = timezone.now()
    diff = records.diffs(stack.team_id).create(
        team_id=stack.team_id,
        stack=stack,
        target_team_id=params.caller.target_team_id,
        encrypted_description=crypto.encrypt(json.dumps(params.description).encode()),
        description_hash=description_hash(params.description),
        kinds=sorted(description_kinds(params.description)),
        source_repository=params.source.repository,
        source_branch=params.source.branch,
        source_commit=params.source.commit,
        status=DiffStatus.FAILED.value if refusal else DiffStatus.RUNNING.value,
        diff=empty_diff([refusal]) if refusal else None,
        expires_at=now + DIFF_LIFETIME,
        deadline_at=now + DIFF_DEADLINE,
        created_by_id=params.caller.user_id,
        created_by_grant=grants.grant_dict(params.caller.grant),
        run_scopes=scopes,
    )
    if refusal is None:
        team_id, diff_id = diff.team_id, diff.id
        transaction.on_commit(lambda: _dispatch_diff(team_id, diff_id), using=WRITER_DB)
    return diff


def _dispatch_diff(team_id: int, diff_id: UUID) -> None:
    try:
        temporal_client.start_diff_workflow(team_id=team_id, diff_id=diff_id)
    except Exception:
        logger.exception("stacks_diff_dispatch_failed", diff_id=str(diff_id))
        records.diffs(team_id).filter(id=diff_id, status=DiffStatus.RUNNING.value).update(
            status=DiffStatus.FAILED.value, diff=empty_diff([runner_unavailable_error()])
        )


def _visible_bindings(team_id: int) -> QuerySet[StackBinding]:
    return records.bindings(team_id).filter(status__in=records.MANAGED_STATUSES).select_related("stack")


def list_bindings(team_id: int, stack_name: str, page: PageRequest) -> Page[StackBinding]:
    stack = get_stack(team_id, stack_name)
    return select_page(_visible_bindings(stack.team_id).filter(stack_id=stack.id).order_by("kind", "key"), page)


def find_bindings(team_id: int, *, kind: str, entity_id: str) -> list[StackBinding]:
    """The binding of an entity, by its id or, for a kind whose definition key is its natural name such as an
    event name or a wiki path, by that name."""
    match = Q(entity_id=entity_id)
    if kind in engine_adapter.natural_key_kinds() or engine_adapter.ownership_scope(kind) == "organization":
        match |= Q(key=entity_id)
    return list(
        _visible_bindings(resolve_effective_team_id(team_id))
        .filter(match, stack__target_team_id=team_id, kind=kind)
        .order_by("id")[:1]
    )


def managed_entity_ids(team_id: int, kind: str) -> set[str]:
    return set(
        _visible_bindings(resolve_effective_team_id(team_id))
        .filter(stack__target_team_id=team_id, kind=kind)
        .values_list("entity_id", flat=True)
    )


def get_binding(team_id: int, stack_name: str, binding_id: UUID) -> StackBinding:
    stack = get_stack(team_id, stack_name)
    binding = _visible_bindings(stack.team_id).filter(stack_id=stack.id, id=binding_id).first()
    if binding is None:
        raise _error(StackErrorKind.NOT_FOUND, "binding_not_found", "No binding with this id exists for this stack.")
    return binding


def adopt(params: AdoptInput, canonical_ids: dict[tuple[str, str], str]) -> list[StackBinding]:
    """Record pending bindings. `canonical_ids` maps (kind, key) to the id the kind's own API returned."""
    stack = get_or_create_stack(params.team_id, params.stack_name, params.caller)
    lease.recover_if_expired(stack)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        lease.check_unlocked(stack)
        check_organization_kinds(stack, {resource.kind for resource in params.resources})
        natural = engine_adapter.natural_key_kinds()
        recorded = []
        for resource in params.resources:
            if resource.kind in natural:
                records.reserve_natural(stack, resource.kind, resource.key)
            recorded.append(
                _record_pending(stack, resource.kind, resource.key, canonical_ids[(resource.kind, resource.key)])
            )
        records.advance_revision(stack)
    return recorded


def _record_pending(stack: Stack, kind: str, key: str, entity_id: str) -> StackBinding:
    claim = (
        records.managed_in_scope([records.claim_scope(stack, kind)])
        .filter(kind=kind, entity_id=entity_id)
        .exclude(stack_id=stack.id, key=key)
        .select_related("stack")
        .first()
    )
    if claim is not None:
        if claim.stack_id == stack.id:
            raise _error(
                StackErrorKind.CONFLICT,
                "entity_already_bound",
                f"This stack already manages that {kind} as {claim.key}. Adopt it under that key.",
            )
        raise _error(StackErrorKind.CONFLICT, "claimed_by_other_stack", claimed_message(claim))
    existing = records.bindings(stack.team_id).filter(stack_id=stack.id, kind=kind, key=key).first()
    if existing is not None and existing.status == BindingStatus.BOUND.value and existing.entity_id != entity_id:
        raise _error(
            StackErrorKind.CONFLICT,
            "key_already_bound",
            f"The {kind} {key} in this stack already manages another entity. Choose another key.",
        )
    if existing is None:
        try:
            with transaction.atomic(using=WRITER_DB):
                created = _create_pending(stack, kind, key, entity_id)
        except IntegrityError:
            # Another stack's adopt of the same entity committed first.
            raise _error(
                StackErrorKind.CONFLICT,
                "claimed_by_other_stack",
                f"Another stack manages the {kind} {key}. Detach it there first.",
            ) from None
        created.stack = stack
        return created
    if existing.status != BindingStatus.BOUND.value:
        existing.entity_id = entity_id
        existing.status = BindingStatus.PENDING.value
        existing.origin = BindingOrigin.ADOPTED.value
        try:
            with transaction.atomic(using=WRITER_DB):
                existing.save(update_fields=["entity_id", "status", "origin", "updated_at"])
        except IntegrityError:
            raise _error(
                StackErrorKind.CONFLICT,
                "claimed_by_other_stack",
                f"Another stack manages the {kind} {key}. Detach it there first.",
            ) from None
    existing.stack = stack
    return existing


def _create_pending(stack: Stack, kind: str, key: str, entity_id: str) -> StackBinding:
    return records.bindings(stack.team_id).create(
        team_id=stack.team_id,
        stack=stack,
        kind=kind,
        key=key,
        entity_id=entity_id,
        status=BindingStatus.PENDING.value,
        origin=BindingOrigin.ADOPTED.value,
        claim_scope=records.claim_scope(stack, kind),
        owned_fields=sorted(engine_adapter.owned_fields(kind, {})),
    )


def detach(team_id: int, stack_name: str, binding_id: UUID) -> StackBinding:
    found = get_binding(team_id, stack_name, binding_id)
    lease.recover_if_expired(found.stack)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(found.stack)
        lease.check_unlocked(stack)
        # A push that finished meanwhile can have bound a pending binding, so it is read again under the lock.
        binding = _visible_bindings(stack.team_id).filter(stack_id=stack.id, id=binding_id).first()
        if binding is None:
            raise _error(
                StackErrorKind.NOT_FOUND, "binding_not_found", "No binding with this id exists for this stack."
            )
        if binding.status == BindingStatus.PENDING.value:
            # Nothing was pushed for a pending binding, so there is nothing to forget.
            records.bindings(stack.team_id).filter(id=binding.id).delete()
        else:
            records.bindings(stack.team_id).filter(id=binding.id).update(
                status=BindingStatus.DETACHED.value, updated_at=timezone.now()
            )
        binding.status = BindingStatus.DETACHED.value
        # A detached natural key is free for another stack now, as the claim refusal tells that stack.
        records.release_natural(stack)
        records.advance_revision(stack)
    return binding


def engine_bindings(stack: Stack) -> list[dict]:
    rows = records.bindings(stack.team_id).filter(stack_id=stack.id).order_by("kind", "key")
    return [
        {"kind": row.kind, "key": row.key, "entity_id": row.entity_id, "status": row.status, "origin": row.origin}
        for row in rows
    ]


def claimed_elsewhere(stack: Stack, kinds_in_use: set[str]) -> list[dict]:
    """Entities of these kinds that other stacks manage in the same claim scope, for the engine to refuse to adopt."""
    rows = (
        records.managed_in_scope(records.claim_scope(stack, kind) for kind in kinds_in_use)
        .filter(kind__in=sorted(kinds_in_use))
        .exclude(stack_id=stack.id)
        .select_related("stack")
        .order_by("kind", "entity_id")
    )
    return [
        {"kind": row.kind, "entity_id": row.entity_id, "stack": row.stack.name, "repository": row.stack.repository}
        for row in rows
    ]


def diff_source(diff: StackDiff) -> DiffSource:
    return DiffSource(repository=diff.source_repository, branch=diff.source_branch, commit=diff.source_commit)


def set_secret(params: SetSecretInput) -> StackSecret:
    ensure_ready()
    stack = get_or_create_stack(params.team_id, params.stack_name, params.caller)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        secret = secrets.set_secret(stack, params.name, params.value, params.caller.user_id)
        _secrets_changed(stack)
    return secret


def _secrets_changed(stack: Stack) -> None:
    """A diff read the old values, including one still computing, so none of them stays pushable."""
    records.stacks(stack.team_id).filter(id=stack.id).update(secret_revision=stack.secret_revision + 1)
    records.stale_ready_diffs(stack)


def list_secrets(team_id: int, stack_name: str) -> list[StackSecret]:
    return secrets.list_secrets(get_stack(team_id, stack_name))


def delete_secret(team_id: int, stack_name: str, name: str) -> None:
    stack = get_stack(team_id, stack_name)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        secrets.delete_secret(stack, name)
        _secrets_changed(stack)
