"""A stack's record of what it made: saving it as a push goes, and keeping the bindings index true to it.

The record is saved every time the engine rewrites it, so a worker that dies mid-push loses nothing that
already succeeded. One push attempt keeps one version row: its first write takes a new serial, and each later
write replaces the row's bytes and takes the next serial again. Every write moves the serial, so a diff
computed against any earlier record is refused with `stack_moved`. Every save first proves that the attempt
still holds the stack's lease.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog

from .. import engine_adapter
from ..db import WRITER_DB
from ..facade.contracts import StackServiceError
from ..facade.enums import BindingOrigin, BindingStatus, DiffStatus, StackErrorKind
from ..models import Stack, StackBinding, StackDiff, StackNaturalClaim, StackRecordVersion
from . import crypto, managed

logger = structlog.get_logger(__name__)

MANAGED_STATUSES = (BindingStatus.PENDING.value, BindingStatus.BOUND.value)


class RecordMissing(Exception):
    """The stack's serial names a record that is not stored. Treating it as empty would recreate everything."""


def stacks(team_id: int):  # noqa: ANN201 — the queryset type is the model's manager queryset
    return Stack.objects.for_team(team_id, canonical=True).using(WRITER_DB)


def diffs(team_id: int):  # noqa: ANN201
    return StackDiff.objects.for_team(team_id, canonical=True).using(WRITER_DB)


def bindings(team_id: int):  # noqa: ANN201
    return StackBinding.objects.for_team(team_id, canonical=True).using(WRITER_DB)


def versions(team_id: int):  # noqa: ANN201
    return StackRecordVersion.objects.for_team(team_id, canonical=True).using(WRITER_DB)


def planned_changes(result: dict) -> list[dict]:
    """The engine's plan as identities only, unredacted, for admission to reserve. Never returned by an API."""
    return [
        {
            "action": str(change.get("action")),
            "kind": str(change.get("kind")),
            "key": str(change.get("key")),
            "entity_id": str(change["entity_id"]) if change.get("entity_id") else None,
        }
        for change in result.get("changes", [])
    ]


def claim_scope(stack: Stack, kind: str) -> str:
    """Where an entity of this kind can be claimed once: the project, or the organization for a kind such as a
    context page that every project of the organization shares."""
    if engine_adapter.ownership_scope(kind) == "organization":
        return f"organization:{stack.organization_id}"
    return f"team:{stack.target_team_id}"


def reserve_natural(stack: Stack, kind: str, key: str) -> None:
    """Take a natural identity for the stack, or refuse with `claimed_by_other_stack`. Call in a transaction."""
    scope = claim_scope(stack, kind)
    held = StackNaturalClaim.all_teams.using(WRITER_DB).filter(claim_scope=scope, kind=kind, key=key).first()
    if held is not None and held.stack_id == stack.id:
        return
    if held is None:
        try:
            with transaction.atomic(using=WRITER_DB):
                StackNaturalClaim.objects.for_team(stack.team_id, canonical=True).using(WRITER_DB).create(
                    team_id=stack.team_id, stack=stack, claim_scope=scope, kind=kind, key=key
                )
            return
        except IntegrityError:
            held = StackNaturalClaim.all_teams.using(WRITER_DB).filter(claim_scope=scope, kind=kind, key=key).first()
    other = held.stack if held is not None else None
    where = f" from {other.repository}" if other is not None and other.repository else ""
    raise StackServiceError(
        StackErrorKind.CONFLICT,
        "claimed_by_other_stack",
        f"The {kind} {key} is planned or managed by the stack {other.name if other else 'another stack'}{where}. "
        "Remove it from one of the two stacks.",
    )


def release_natural(stack: Stack) -> None:
    """Release the natural identities the stack no longer manages. Call with the stack row locked."""
    kept = set(
        bindings(stack.team_id).filter(stack_id=stack.id, status__in=MANAGED_STATUSES).values_list("kind", "key")
    )
    for claim in StackNaturalClaim.all_teams.using(WRITER_DB).filter(stack_id=stack.id):
        if (claim.kind, claim.key) not in kept:
            claim.delete()


def managed_in_scope(scopes: Iterable[str]):  # noqa: ANN201
    """Managed bindings in these claim scopes, across every project they cover."""
    return StackBinding.all_teams.using(WRITER_DB).filter(
        claim_scope__in=sorted(set(scopes)), status__in=MANAGED_STATUSES
    )


def locked_stack(stack: Stack) -> Stack:
    """The stack row, locked for the rest of the transaction."""
    return stacks(stack.team_id).select_for_update().get(id=stack.id)


def stale_ready_diffs(stack: Stack, *, keep: UUID | None = None) -> None:
    """Ready diffs no longer say what a push would do. A push refuses them, so none keeps its saved bytes."""
    queryset = diffs(stack.team_id).filter(stack_id=stack.id, status=DiffStatus.READY.value)
    if keep is not None:
        queryset = queryset.exclude(id=keep)
    queryset.update(status=DiffStatus.STALE.value, encrypted_saved_diff=None)


def advance_revision(stack: Stack) -> None:
    """Record a change to the bindings. Call with the stack row locked."""
    stacks(stack.team_id).filter(id=stack.id).update(revision=stack.revision + 1, updated_at=timezone.now())
    stale_ready_diffs(stack)
    managed.forget_team(stack.team_id)


def sources_by_identity(description: dict) -> dict[tuple[str, str], tuple[str, str]]:
    sources: dict[tuple[str, str], tuple[str, str]] = {}
    for resource in description.get("resources", []):
        source = resource.get("source") or {}
        sources[(str(resource.get("kind")), str(resource.get("key")))] = (
            str(source.get("file", "")),
            str(source.get("export", "")),
        )
    return sources


def description_of(diff: StackDiff) -> dict:
    return json.loads(crypto.decrypt(diff.encrypted_description))


def latest_record(stack: Stack) -> bytes | None:
    if stack.serial == 0:
        return None
    version = versions(stack.team_id).filter(stack_id=stack.id, serial=stack.serial).only("encrypted_record").first()
    if version is None:
        raise RecordMissing(f"stack {stack.id} has serial {stack.serial} and no stored record")
    return crypto.decrypt(version.encrypted_record)


def record_missing_error() -> dict:
    return {
        "code": "record_missing",
        "message": "PostHog cannot find this stack's last saved record. Contact support before you push again.",
    }


class LeaseLost(Exception):
    pass


def save_record(stack: Stack, *, attempt_id: UUID, generation: int, diff: StackDiff, record: bytes) -> None:
    """Store one record a push reported. Raises LeaseLost when the attempt no longer holds the stack."""
    encrypted = crypto.encrypt(record)
    with transaction.atomic(using=WRITER_DB):
        current = locked_stack(stack)
        if current.lease_attempt_id != attempt_id or current.lease_generation != generation:
            raise LeaseLost(str(attempt_id))
        serial = current.serial + 1
        updated = (
            versions(stack.team_id)
            .filter(stack_id=stack.id, push_attempt_id=attempt_id)
            .update(serial=serial, encrypted_record=encrypted)
        )
        if not updated:
            versions(stack.team_id).create(
                team_id=stack.team_id,
                stack=current,
                serial=serial,
                encrypted_record=encrypted,
                pushed_by_diff_id=diff.id,
                push_attempt_id=attempt_id,
            )
        stacks(stack.team_id).filter(id=stack.id).update(
            serial=serial, repository=diff.source_repository, updated_at=timezone.now()
        )


def attempt_saved_a_record(team_id: int, attempt_id: UUID) -> bool:
    return versions(team_id).filter(push_attempt_id=attempt_id).exists()


def _adopted_in_diff(diff: StackDiff) -> set[tuple[str, str]]:
    changes = (diff.diff or {}).get("changes", [])
    return {(str(change["kind"]), str(change["key"])) for change in changes if change.get("action") == "adopt"}


def rebuild_bindings(
    stack: Stack,
    diff: StackDiff,
    description: dict,
    record: bytes | None,
    adopted: frozenset[tuple[str, str]] = frozenset(),
) -> list[dict]:
    """Make the bindings index match a record. Call with the stack row locked. Returns errors for entities
    it could not bind."""
    errors: list[dict] = []
    sources = sources_by_identity(description)
    bodies = {(str(r["kind"]), str(r["key"])): r.get("body") or {} for r in description.get("resources", [])}
    rows = {(row.kind, row.key): row for row in bindings(stack.team_id).filter(stack_id=stack.id)}
    held = {(item.kind, item.key): item for item in engine_adapter.bindings_in(record)} if record else {}
    adopted_here = _adopted_in_diff(diff) | set(adopted)

    for identity, row in rows.items():
        if identity in held and row.status != BindingStatus.DETACHED.value:
            continue
        keep = row.status == BindingStatus.PENDING.value or (
            row.status == BindingStatus.DETACHED.value and identity in sources
        )
        if not keep:
            row.delete()

    claimed = _bound_elsewhere(stack, held.values())
    for identity, item in held.items():
        row = rows.get(identity)
        if row is not None and row.status == BindingStatus.DETACHED.value:
            continue
        if (item.kind, item.entity_id) in claimed:
            errors.append(
                {
                    "code": "claimed_by_other_stack",
                    "message": f"The {item.kind} {item.key} is managed by another stack. Detach it there, then push again.",
                    "kind": item.kind,
                    "key": item.key,
                }
            )
            continue
        was_adopted = row is not None and row.origin == BindingOrigin.ADOPTED.value
        origin = BindingOrigin.ADOPTED if was_adopted or identity in adopted_here else BindingOrigin.CREATED
        source_file, source_export = sources.get(identity, ("", ""))
        values = {
            "entity_id": item.entity_id,
            "status": BindingStatus.BOUND.value,
            "origin": origin.value,
            "claim_scope": claim_scope(stack, item.kind),
            "owned_fields": sorted(engine_adapter.owned_fields(item.kind, bodies.get(identity, {}))),
            "source_file": source_file,
            "source_export": source_export,
        }
        bindings(stack.team_id).update_or_create(
            stack=stack,
            kind=item.kind,
            key=item.key,
            create_defaults={"team_id": stack.team_id, **values},
            defaults=values,
        )
    managed.forget_team(stack.team_id)
    return errors


def _bound_elsewhere(stack: Stack, records: Iterable[engine_adapter.BindingRecord]) -> set[tuple[str, str]]:
    pairs = {(item.kind, item.entity_id) for item in records}
    if not pairs:
        return set()
    scopes = {claim_scope(stack, kind) for kind, _ in pairs}
    return {
        (kind, entity_id)
        for kind, entity_id in managed_in_scope(scopes)
        .filter(entity_id__in=sorted({entity_id for _, entity_id in pairs}))
        .exclude(stack_id=stack.id)
        .values_list("kind", "entity_id")
        if (kind, entity_id) in pairs
    }
