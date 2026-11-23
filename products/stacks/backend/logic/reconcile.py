"""Accounting for an uncertain push before the stack pushes again.

A push that stopped without a known outcome may have created an entity whose id never reached the record. The
next diff then plans to create it again. That diff lists, as warnings, the entities PostHog holds with the name
of a definition it plans to create that no stack manages, so a person adopts them or confirms the creates. The
stack stays uncertain until a person reconciles with such a diff.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from django.db import transaction
from django.utils.dateparse import parse_datetime

from .. import engine_adapter
from ..db import WRITER_DB
from ..facade.contracts import ReconcileInput, StackServiceError
from ..facade.enums import DiffStatus, StackErrorKind
from ..models import Stack
from . import lease, records
from .stacks import get_diff_for_update, get_stack, stack_moved_error

# Pages of entities read per kind. A kind with more is reported as not fully checked.
MAX_PAGES = 20
PAGE_SIZE = 100


def _created_before(body: dict, since: datetime | None) -> bool:
    created = parse_datetime(str(body.get("created_at") or "")) if since is not None else None
    return created is not None and since is not None and created < since


def unrecorded_creates(stack: Stack, result: dict, credentials: engine_adapter.EngineCredentials) -> list[dict]:
    """Warnings for entities the interrupted push may have created without recording them."""
    wanted: dict[str, dict[str, str]] = defaultdict(dict)
    for change in result.get("changes", []):
        if change.get("action") in ("create", "recreate"):
            wanted[str(change["kind"])][str(change.get("name") or change["key"])] = str(change["key"])
    warnings: list[dict] = []
    for kind in sorted(wanted):
        names = wanted[kind]
        managed = set(
            records.managed_in_scope([records.claim_scope(stack, kind)])
            .filter(kind=kind)
            .values_list("entity_id", flat=True)
        )
        found: dict[str, list[dict]] = defaultdict(list)
        cursor: str | None = None
        complete = False
        try:
            for _ in range(MAX_PAGES):
                page = engine_adapter.read_entities(kind, credentials, cursor=cursor, limit=PAGE_SIZE)
                for item in page.results:
                    if (
                        item.name in names
                        and item.entity_id not in managed
                        and not _created_before(item.body, stack.uncertain_since)
                    ):
                        found[names[item.name]].append({"entity_id": item.entity_id, "name": item.name})
                cursor = page.next_cursor
                if cursor is None:
                    complete = True
                    break
        except engine_adapter.EngineFailure:
            complete = False
        for key in sorted(found):
            warnings.append(
                {
                    "code": "possible_unrecorded_create",
                    "kind": kind,
                    "key": key,
                    "message": f"The interrupted push may already have created the {kind} {key}. Adopt one of "
                    "these entities instead of creating another, or reconcile to let the push create it.",
                    "entities": found[key],
                }
            )
        if not complete:
            warnings.append(
                {
                    "code": "unrecorded_creates_unchecked",
                    "kind": kind,
                    "key": None,
                    "message": f"PostHog could not read every {kind} to look for entities the interrupted push may "
                    "have created. Check them in PostHog before you reconcile.",
                    "entities": [],
                }
            )
    return warnings


def reconcile(params: ReconcileInput) -> tuple[Stack, int]:
    """A person accepts a ready diff computed since the uncertain push, warnings included. Returns the stack and
    how many warnings they acknowledged."""
    stack = get_stack(params.team_id, params.stack_name)
    lease.recover_if_expired(stack)
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(stack)
        lease.check_unlocked(stack)
        if not stack.needs_reconcile:
            raise StackServiceError(
                StackErrorKind.CONFLICT, "nothing_to_reconcile", "This stack has no uncertain push to reconcile."
            )
        diff = get_diff_for_update(stack, params.diff_id)
        if diff.target_team_id != params.caller.target_team_id:
            raise StackServiceError(
                StackErrorKind.NOT_FOUND, "diff_not_found", "No diff with this id exists for this project."
            )
        if diff.status == DiffStatus.STALE.value:
            raise stack_moved_error()
        if diff.status != DiffStatus.READY.value:
            raise StackServiceError(
                StackErrorKind.CONFLICT,
                "diff_not_ready",
                "Reconcile with a ready diff computed since the uncertain push. Run diff again and wait for it.",
            )
        # The uncertain push moved the revision, so a diff with the current one was computed after it.
        if (diff.base_serial, diff.base_revision, diff.base_secret_revision) != (
            stack.serial,
            stack.revision,
            stack.secret_revision,
        ):
            raise stack_moved_error()
        records.stacks(stack.team_id).filter(id=stack.id).update(needs_reconcile=False, uncertain_since=None)
        stack.needs_reconcile = False
        acknowledged = len((diff.diff or {}).get("warnings", []))
    return stack, acknowledged
