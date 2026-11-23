"""The engine work behind a diff and a push. The stacks Temporal activities call these.

Each run acts as the caller that admitted it, for the exact project and scopes checked at admission. Before
it mints a token the worker checks again that the caller and the credential that asked may still run it.
"""

from __future__ import annotations

import threading
import contextvars
from collections.abc import Callable
from uuid import UUID

from django.db import connections, transaction
from django.utils import timezone

import structlog

from .. import engine_adapter
from ..db import WRITER_DB
from ..facade.contracts import StackServiceError
from ..facade.enums import DiffStatus, PushStatus
from ..models import Stack, StackDiff
from . import cleanup, credentials, crypto, grants, lease, reconcile, records, secrets, validation
from .credentials import CallerUnavailable
from .stacks import (
    bound_kinds,
    check_organization_kinds,
    claimed_elsewhere,
    empty_diff,
    engine_bindings,
    stack_moved_error,
)

logger = structlog.get_logger(__name__)


def _run_failed_error() -> dict:
    return {
        "code": "run_failed",
        "message": "PostHog could not finish this run. Try again, and contact support if it keeps failing.",
    }


def _caller_error(error: CallerUnavailable) -> dict:
    return {"code": "caller_unavailable", "message": str(error)}


def _engine_input(stack: Stack, description: dict) -> object:
    kinds_in_use = {str(resource["kind"]) for resource in description.get("resources", [])}
    return engine_adapter.build_input(description, engine_bindings(stack), claimed_elsewhere(stack, kinds_in_use))


def compute_diff(team_id: int, diff_id: UUID) -> None:
    cleanup.sweep_workdir()
    diff = records.diffs(team_id).filter(id=diff_id).select_related("stack").first()
    if diff is None or diff.status != DiffStatus.RUNNING.value:
        return
    if diff.deadline_at <= timezone.now():
        _finish_diff(diff, DiffStatus.FAILED, empty_diff([cleanup.timed_out_error()]), None, set())
        return
    stack = diff.stack
    base = (stack.serial, stack.revision, stack.secret_revision)
    description = records.description_of(diff)
    names = secrets.secret_names(description)
    values: dict[str, str] = {}
    token = None
    try:
        if missing := secrets.missing_secrets(stack, names):
            _finish_diff(diff, DiffStatus.FAILED, empty_diff([secrets.missing_secrets_error(missing)]), None, set())
            return
        authority = grants.check_grant(
            user_id=diff.created_by_id, target_team_id=diff.target_team_id, grant=diff.created_by_grant
        )
        record = records.latest_record(stack)
        engine_input = _engine_input(stack, description)
        values = secrets.secret_values(stack, names)
        token, engine_credentials = credentials.mint(
            user=authority.user,
            target_team_id=diff.target_team_id,
            scopes=authority.narrow(list(diff.run_scopes)),
            secret_values=values,
            expires_at=authority.expires_at,
        )
        outcome = engine_adapter.diff(engine_input, record, engine_credentials)
        warnings = (
            reconcile.unrecorded_creates(stack, outcome.diff, engine_credentials)
            if stack.needs_reconcile and not outcome.diff.get("errors")
            else []
        )
    except engine_adapter.EngineFailure as failure:
        _finish_diff(diff, DiffStatus.FAILED, empty_diff(failure.errors), None, set(values.values()))
        return
    except CallerUnavailable as error:
        _finish_diff(diff, DiffStatus.FAILED, empty_diff([_caller_error(error)]), None, set(values.values()))
        return
    except records.RecordMissing:
        logger.exception("stacks_record_missing", diff_id=str(diff_id))
        _finish_diff(diff, DiffStatus.FAILED, empty_diff([records.record_missing_error()]), None, set())
        return
    except Exception:
        logger.exception("stacks_diff_failed", diff_id=str(diff_id))
        _finish_diff(diff, DiffStatus.FAILED, empty_diff([_run_failed_error()]), None, set(values.values()))
        return
    finally:
        credentials.revoke(token.id if token is not None else None)
    failed = bool(outcome.diff.get("errors")) or not outcome.saved_diff
    _publish_diff(
        diff,
        DiffStatus.FAILED if failed else DiffStatus.READY,
        {**outcome.diff, "warnings": warnings},
        None if failed else outcome.saved_diff,
        set(values.values()),
        base=base,
        planned=records.planned_changes(outcome.diff),
    )


def _finish_diff(
    diff: StackDiff, status: DiffStatus, result: dict, saved_diff: bytes | None, secret_values: set[str]
) -> None:
    records.diffs(diff.team_id).filter(id=diff.id, status=DiffStatus.RUNNING.value).update(
        status=status.value,
        diff=validation.redact(result, secret_values),
        encrypted_saved_diff=crypto.encrypt(saved_diff) if saved_diff else None,
        updated_at=timezone.now(),
    )


def _publish_diff(
    diff: StackDiff,
    status: DiffStatus,
    result: dict,
    saved_diff: bytes | None,
    secret_values: set[str],
    *,
    base: tuple[int, int, int],
    planned: list[dict],
) -> None:
    """Publish a computed diff. It is ready only if neither the record, the bindings nor the secrets moved meanwhile.

    A ready diff never clears an uncertain push by itself: a person reconciles with it first.
    """
    encrypted = crypto.encrypt(saved_diff) if saved_diff else None
    base_serial, base_revision, base_secret_revision = base
    with transaction.atomic(using=WRITER_DB):
        stack = records.locked_stack(diff.stack)
        current = (stack.serial, stack.revision, stack.secret_revision) == base
        if status == DiffStatus.READY and not current:
            status, encrypted = DiffStatus.STALE, None
        records.diffs(diff.team_id).filter(id=diff.id, status=DiffStatus.RUNNING.value).update(
            status=status.value,
            diff=validation.redact(result, secret_values),
            encrypted_saved_diff=encrypted,
            base_serial=base_serial,
            base_revision=base_revision,
            base_secret_revision=base_secret_revision,
            planned=planned,
            updated_at=timezone.now(),
        )


class RunCancelled(Exception):
    """Temporal cancelled the activity, so the run stops at its next checkpoint."""


class _Heartbeat:
    """Extends the lease from a thread while the run works, and notes when the lease or the activity is lost.

    A heartbeat Temporal refuses, a cancellation, or a lease the database no longer extends all mean the run must
    stop: the next checkpoint raises the engine's abort.
    """

    def __init__(self, stack: Stack, attempt_id: UUID, generation: int, beat: Callable[[], None]) -> None:
        self.stack = stack
        self.attempt_id = attempt_id
        self.generation = generation
        self.beat = beat
        self.lost = False
        self._stop = threading.Event()
        context = contextvars.copy_context()
        self._thread = threading.Thread(target=lambda: context.run(self._run), daemon=True)

    def _tick(self) -> bool:
        try:
            self.beat()
            return lease.extend(self.stack.team_id, self.stack.id, self.attempt_id, self.generation)
        except Exception:
            logger.warning("stacks_push_heartbeat_failed", attempt_id=str(self.attempt_id), exc_info=True)
            return False

    def _run(self) -> None:
        try:
            while not self._stop.wait(lease.HEARTBEAT.total_seconds()):
                if not self._tick():
                    self.lost = True
                    return
        finally:
            connections.close_all()

    def __enter__(self) -> _Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _check_still_pushable(stack: Stack, diff: StackDiff, description: dict) -> None:
    """What admission checked, again, right before the credential is minted: nothing moved, and a shared kind is
    still allowed."""
    current = records.stacks(stack.team_id).get(id=stack.id)
    if (
        current.serial != diff.base_serial
        or current.revision != diff.base_revision
        or current.secret_revision != diff.base_secret_revision
        or diff.encrypted_saved_diff is None
    ):
        raise engine_adapter.EngineFailure([{"code": "stack_moved", "message": stack_moved_error().message}])
    used = {str(resource["kind"]) for resource in description.get("resources", [])} | set(bound_kinds(current))
    try:
        check_organization_kinds(current, used)
    except StackServiceError as error:
        raise engine_adapter.EngineFailure([{"code": error.code, "message": error.message}]) from error


def run_push(team_id: int, diff_id: UUID, attempt_id: UUID, beat: Callable[[], None] = lambda: None) -> None:
    cleanup.sweep_workdir()
    diff = records.diffs(team_id).filter(id=diff_id, push_attempt_id=attempt_id).select_related("stack").first()
    if diff is None or diff.push_status != PushStatus.RUNNING.value or diff.push_generation is None:
        return
    stack = diff.stack
    generation = diff.push_generation
    if not lease.claim(stack, attempt_id, generation):
        # The lease expired before the worker started, so a takeover closes this attempt, not the worker.
        return
    abort = engine_adapter.abort_run()
    values: dict[str, str] = {}
    token = None
    outcome: engine_adapter.PushOutcome | None = None
    errors: list[dict] = []
    status = PushStatus.FAILED
    heartbeat = _Heartbeat(stack, attempt_id, generation, beat)

    def on_record(record: bytes) -> None:
        if not record:
            return
        if heartbeat.lost:
            raise abort("lease lost")
        try:
            records.save_record(stack, attempt_id=attempt_id, generation=generation, diff=diff, record=record)
        except Exception as error:
            # The engine goes on only while what it did is stored, whatever stopped the store.
            logger.warning("stacks_push_checkpoint_failed", attempt_id=str(attempt_id), error=type(error).__name__)
            raise abort("checkpoint failed") from None

    try:
        # The heartbeat starts before the slow preparation, so the lease never lapses while the worker is alive.
        with heartbeat:
            description = records.description_of(diff)
            names = secrets.secret_names(description)
            authority = grants.check_grant(
                user_id=diff.pushed_by_id, target_team_id=diff.target_team_id, grant=diff.pushed_by_grant
            )
            record = records.latest_record(stack)
            _check_still_pushable(stack, diff, description)
            engine_input = _engine_input(stack, description)
            values = secrets.secret_values(stack, names)
            token, engine_credentials = credentials.mint(
                user=authority.user,
                target_team_id=diff.target_team_id,
                scopes=authority.narrow(list(diff.push_scopes)),
                secret_values=values,
                expires_at=authority.expires_at,
            )
            if not lease.register_token(stack, attempt_id, generation, token.id):
                raise abort("lease lost")
            outcome = engine_adapter.push(
                engine_input, crypto.decrypt(diff.encrypted_saved_diff), record, engine_credentials, on_record
            )
            # The engine reports the final record through `on_record` too. Saving it again changes nothing, and
            # it covers a final record the engine returned without reporting.
            if outcome.record:
                on_record(outcome.record)
        errors = list(outcome.errors)
        status = PushStatus.SUCCEEDED if not errors else PushStatus.FAILED
        if any(error.get("code") == "stack_interrupted" for error in errors):
            # The engine stopped mid-change, so a change may have reached PostHog without being recorded.
            status = PushStatus.UNCERTAIN
    except abort:
        logger.warning("stacks_push_aborted", attempt_id=str(attempt_id))
        errors, status = [lease.interrupted_error()], PushStatus.UNCERTAIN
    except engine_adapter.EngineFailure as failure:
        errors = failure.errors
    except CallerUnavailable as error:
        errors = [_caller_error(error)]
    except records.RecordMissing:
        logger.exception("stacks_record_missing", diff_id=str(diff_id))
        errors = [records.record_missing_error()]
    except Exception:
        logger.exception("stacks_push_failed", diff_id=str(diff_id))
        errors = [_run_failed_error()]
        # The engine may have changed PostHog before the failure, so the outcome is unknown.
        status = PushStatus.UNCERTAIN
    finally:
        # Revoking the token is separate from recording the outcome: a failure here never loses what succeeded.
        credentials.revoke(token.id if token is not None else None)
    # Closing does nothing when a takeover already closed the attempt, and closes it as uncertain when the lease
    # expired meanwhile.
    lease.close_attempt(
        stack,
        attempt_id,
        validation.redact({"errors": errors}, set(values.values()))["errors"],
        status=status,
        adopted=outcome.adopted if outcome is not None else frozenset(),
        generation=generation,
    )
