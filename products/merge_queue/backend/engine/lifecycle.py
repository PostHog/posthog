"""Engine lifecycle — the enroll → trial → merge/eject state machine.

    eligible → enrolled → trialing → (merged | ejected)
                             ↑__________________|  (re-enroll at back of line)

This is the deterministic core. It consults the `GatedProvider` at its branch points
(`select_strategy`, `triage_ejection`); with `cowboy=None` those resolve to the deterministic
defaults. Every transition emits exactly one `QueueEvent` through `observability.emit`.

Two collaborators are injected so the engine stays standalone and testable:
- `set_trial_launcher` — how a PENDING trial is dispatched (Temporal in production).
- `set_master_head_resolver` — how master HEAD is resolved (the GitHub adapter in production).

Side effects on GitHub (the actual merge) go through the module `ShadowGuard`, which is
currently shadow — it records, it does not act.
"""

import logging
from collections.abc import Callable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from asgiref.sync import async_to_sync

from products.merge_queue.backend import flaky, observability
from products.merge_queue.backend.engine import projected_state, strategies
from products.merge_queue.backend.facade.decisions import (
    DeterministicDefaults,
    Disposition,
    GatedProvider,
    PartitionSignals,
    TrialResult,
)
from products.merge_queue.backend.facade.types import Actor, PRRef
from products.merge_queue.backend.models import (
    Enrollment,
    EnrollmentState,
    Partition,
    QueueEventType,
    Slot,
    SlotState,
    Strategy,
    Trial,
    TrialState,
)
from products.merge_queue.backend.shadow import ShadowGuard

logger = logging.getLogger(__name__)

# ---- injected collaborators (defaults keep the engine importable & testable) ----
TrialLauncher = Callable[[UUID], None]
MasterHeadResolver = Callable[[str], str]

_oracle = flaky.default_oracle()
_shadow = ShadowGuard(github=None)  # currently shadow — record, don't act


def _default_launcher(trial_id: UUID) -> None:
    # noqa: PLC0415 — keep temporalio off the engine's import path; load it only when a
    # trial is actually dispatched (the web process imports lifecycle, not Temporal).
    from products.merge_queue.backend.temporal.client import start_trial_workflow  # noqa: PLC0415

    start_trial_workflow(str(trial_id))


def _no_master_head(repo: str) -> str:
    raise NotImplementedError("install a master-head resolver via set_master_head_resolver()")


_launch_trial: TrialLauncher = _default_launcher
_master_head: MasterHeadResolver = _no_master_head


def set_trial_launcher(fn: TrialLauncher) -> None:
    global _launch_trial
    _launch_trial = fn


def set_master_head_resolver(fn: MasterHeadResolver) -> None:
    global _master_head
    _master_head = fn


def set_flaky_oracle(oracle: flaky.FlakyOracle) -> None:
    global _oracle
    _oracle = oracle


def set_shadow_guard(guard: ShadowGuard) -> None:
    global _shadow
    _shadow = guard


def shadow_guard() -> ShadowGuard:
    return _shadow


# ---- decision provider wiring ----
class _NoPromotion:
    def is_live(self, hook: str) -> bool:
        return False


def _provider(partition: Partition) -> GatedProvider:
    default = DeterministicDefaults(flaky=_oracle, pinned=lambda _name: Strategy(partition.strategy))
    return GatedProvider(default, cowboy=None, promotion=_NoPromotion(), record_shadow=observability.record_shadow)


def _resolve_strategy(partition: Partition) -> Strategy:
    signals = PartitionSignals(failure_rate=0.0, queue_depth=0, ci_cost_recent=0.0, enrolled_count=0)
    decision = async_to_sync(_provider(partition).select_strategy)(partition.name, signals)
    return decision.strategy


# ---- public engine entry points ----
def enroll_pr(pr: PRRef, *, actor: Actor, partition: Partition, approval_ref: str = "") -> Enrollment:
    """Create an Enrollment + one Slot at the back of `partition`'s line, then advance."""
    with transaction.atomic():
        enrollment = Enrollment.objects.create(
            repo=pr.repo,
            number=pr.number,
            head_sha=pr.head_sha,
            state=EnrollmentState.ACTIVE,
            approval_ref=approval_ref,
            enrolled_by_id=actor.id,
            enrolled_by_kind=str(actor.kind),
        )
        slot = Slot.objects.create(
            enrollment=enrollment,
            partition=partition,
            state=SlotState.ENROLLED,
            enqueued_at=timezone.now(),  # ORDERING KEY — fresh enqueue → back of line
        )
        observability.emit(QueueEventType.ENROLLED, actor=actor, enrollment=enrollment, slot=slot, partition=partition)
    advance(partition)
    return enrollment


def advance(partition: Partition) -> None:
    """Drive the partition: start eligible trials, merge mergeable enrollments. Idempotent.

    A frozen partition is inert — no trials start and nothing merges. In-flight trials still
    finish and persist their results (slots reach GREEN); those are acted on only after
    unfreeze. Callers load the partition fresh right before advancing, so `is_frozen` reflects
    a freeze that has already committed.
    """
    if partition.is_frozen:
        return
    strategy = _resolve_strategy(partition)
    changed = True
    while changed:
        changed = False
        for slot in _line(partition, SlotState.ENROLLED):
            if _can_start_trial(slot, strategy):
                start_trial(slot, strategy)
                changed = True
        for enrollment in _active_enrollments_with_all_green(partition):
            if _mergeable(enrollment, strategy):
                merge_enrollment(enrollment, partition)
                changed = True


def start_trial(slot: Slot, strategy: Strategy, *, flaky_retried: bool = False) -> Trial:
    """Open a full-suite trial for `slot` against its projected state and dispatch it."""
    master_head = _master_head(slot.enrollment.repo)
    projected = projected_state.build(slot, strategy, master_head_sha=master_head)
    with transaction.atomic():
        trial = Trial.objects.create(
            partition=slot.partition,
            state=TrialState.PENDING,
            projected_base_sha=projected.base_sha,
            projected_head_shas=projected.predecessor_shas,
            flaky_retried=flaky_retried,
        )
        trial.slots.add(slot)
        slot.state = SlotState.TRIALING
        slot.current_trial = trial
        slot.save(update_fields=["state", "current_trial", "updated_at"])
        observability.emit(
            QueueEventType.TRIAL_STARTED,
            enrollment=slot.enrollment,
            slot=slot,
            trial=trial,
            partition=slot.partition,
            payload={"flaky_retried": flaky_retried, "projected_base_sha": projected.base_sha},
        )
    _launch_trial(trial.id)
    return trial


def on_trial_finished(trial_id: str | UUID, *, passed: bool, failing_tests: list[str] | None = None) -> None:
    """Resolve a finished trial: green → GREEN (maybe merge); red → triage (retry or eject)."""
    trial = Trial.objects.select_related("partition").get(id=trial_id)
    slot = trial.slots.select_related("enrollment", "partition").first()
    if slot is None:
        logger.warning("trial %s has no slot; ignoring", trial_id)
        return

    with transaction.atomic():
        trial.state = TrialState.PASSED if passed else TrialState.FAILED
        trial.finished_at = timezone.now()
        if not passed:
            trial.failing_tests = failing_tests or []
        trial.save(update_fields=["state", "finished_at", "failing_tests"])
        observability.emit(
            QueueEventType.TRIAL_FINISHED,
            enrollment=slot.enrollment,
            slot=slot,
            trial=trial,
            partition=trial.partition,
            payload={"passed": passed, "failing_tests": failing_tests or []},
        )
        if passed:
            slot.state = SlotState.GREEN
            slot.save(update_fields=["state", "updated_at"])

    if passed:
        advance(trial.partition)
        return

    disposition = _triage(trial, slot, failing_tests or [])
    if disposition is Disposition.RETRY_FLAKY:
        start_trial(slot, _resolve_strategy(trial.partition), flaky_retried=True)
        return
    _eject(slot, failing_tests or [])
    advance(trial.partition)


def merge_enrollment(enrollment: Enrollment, partition: Partition) -> None:
    """Merge a fully-green enrollment (shadow-guarded), mark it terminal, emit MERGED.

    `advance` can run concurrently (e.g. two trial completions landing at once), so the
    ACTIVE → MERGED transition is an atomic conditional claim: only the caller that flips the
    row out of ACTIVE proceeds. A loser sees zero rows updated and returns, so the merge side
    effect and the MERGED event each happen exactly once.
    """
    now = timezone.now()
    with transaction.atomic():
        claimed = Enrollment.objects.filter(id=enrollment.id, state=EnrollmentState.ACTIVE).update(
            state=EnrollmentState.MERGED, merged_at=now, updated_at=now
        )
        if not claimed:
            return
        enrollment.state = EnrollmentState.MERGED
        enrollment.merged_at = now
        _shadow.merge(repo=enrollment.repo, number=enrollment.number, sha=enrollment.head_sha)
        observability.emit(
            QueueEventType.MERGED, enrollment=enrollment, partition=partition, payload={"head_sha": enrollment.head_sha}
        )


def _eject(slot: Slot, failing_tests: list[str]) -> None:
    """Eject the slot's enrollment (terminal). Re-enroll is a fresh enroll → back of line."""
    enrollment = slot.enrollment
    with transaction.atomic():
        slot.state = SlotState.EJECTED
        slot.save(update_fields=["state", "updated_at"])
        enrollment.state = EnrollmentState.EJECTED
        enrollment.ejected_at = timezone.now()
        enrollment.eject_count = enrollment.eject_count + 1
        enrollment.save(update_fields=["state", "ejected_at", "eject_count", "updated_at"])
        observability.emit(
            QueueEventType.EJECTED,
            enrollment=enrollment,
            slot=slot,
            partition=slot.partition,
            payload={"failing_tests": failing_tests},
        )


# ---- decision: triage ----
def _triage(trial: Trial, slot: Slot, failing_tests: list[str]) -> Disposition:
    pr = PRRef(repo=slot.enrollment.repo, number=slot.enrollment.number, head_sha=slot.enrollment.head_sha)
    result = TrialResult(
        trial_id=trial.id,
        pr=pr,
        partition=trial.partition.name,
        failing_tests=failing_tests,
        attempt=slot.trials.count(),
        log_ref=trial.ci_run_ref,
    )
    decision = async_to_sync(_provider(trial.partition).triage_ejection)(result)
    return decision.disposition


# ---- scheduling helpers ----
def _line(partition: Partition, state: SlotState) -> list[Slot]:
    return list(
        Slot.objects.filter(partition=partition, state=state, enrollment__state=EnrollmentState.ACTIVE)
        .select_related("enrollment", "partition")
        .order_by("enqueued_at", "id")
    )


def _can_start_trial(slot: Slot, strategy: Strategy) -> bool:
    if strategies.is_concurrent(strategy):  # optimistic: independent, start immediately
        return True
    # serial: start once the single predecessor has passed (we validate on top of it)
    predecessor = projected_state.predecessor_slot(slot)
    return predecessor is None or predecessor.state == SlotState.GREEN


def _active_enrollments_with_all_green(partition: Partition) -> list[Enrollment]:
    enrollment_ids = (
        Slot.objects.filter(partition=partition, enrollment__state=EnrollmentState.ACTIVE)
        .values_list("enrollment_id", flat=True)
        .distinct()
    )
    out: list[Enrollment] = []
    for enrollment in Enrollment.objects.filter(id__in=list(enrollment_ids), state=EnrollmentState.ACTIVE):
        slots = list(enrollment.slots.all())
        if slots and all(s.state == SlotState.GREEN for s in slots):
            out.append(enrollment)
    return out


def _mergeable(enrollment: Enrollment, strategy: Strategy) -> bool:
    slots = list(enrollment.slots.select_related("partition").all())
    if not slots or any(s.state != SlotState.GREEN for s in slots):
        return False
    # serial ordering guard: a slot merges only once everything ahead of it has left the line
    for slot in slots:
        if not strategies.is_concurrent(strategy) and projected_state.predecessor_slot(slot) is not None:
            return False
    return True
