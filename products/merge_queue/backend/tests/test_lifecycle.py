import pytest

from django.utils import timezone

from products.merge_queue.backend.engine import lifecycle, projected_state
from products.merge_queue.backend.facade import api
from products.merge_queue.backend.facade.types import Actor, ActorKind, PRRef, Scope
from products.merge_queue.backend.models import (
    Enrollment,
    EnrollmentState,
    QueueEvent,
    QueueEventType,
    Slot,
    SlotState,
    Strategy,
    Trial,
    TrialState,
)

pytestmark = pytest.mark.django_db

ACTOR = Actor(id="7", kind=ActorKind.HUMAN)


def _pr(number: int, sha: str) -> PRRef:
    return PRRef(repo="PostHog/posthog", number=number, head_sha=sha)


def _active_trial(number: int) -> Trial:
    enrollment = Enrollment.objects.get(number=number, state=EnrollmentState.ACTIVE)
    trial = enrollment.slots.get().current_trial
    assert trial is not None
    return trial


class TestOptimisticHappyPath:
    def test_enroll_starts_trial_then_green_merges(self, engine, partition_factory):
        partition_factory(strategy=Strategy.OPTIMISTIC)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)

        trial = _active_trial(1)
        assert trial.state == TrialState.PENDING
        assert engine.launched == [trial.id]
        assert Slot.objects.get().state == SlotState.TRIALING

        lifecycle.on_trial_finished(trial.id, passed=True)

        assert Enrollment.objects.get(number=1).state == EnrollmentState.MERGED
        assert QueueEvent.objects.filter(type=QueueEventType.MERGED).count() == 1


class TestEjectionTriage:
    def test_nonflaky_failure_ejects(self, engine, partition_factory):
        partition_factory(strategy=Strategy.OPTIMISTIC)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        trial = _active_trial(1)

        lifecycle.on_trial_finished(trial.id, passed=False, failing_tests=["test_real"])

        assert Enrollment.objects.get(number=1).state == EnrollmentState.EJECTED
        assert Slot.objects.get().state == SlotState.EJECTED
        assert QueueEvent.objects.filter(type=QueueEventType.EJECTED).count() == 1

    def test_flaky_failure_retries_without_eject(self, engine, partition_factory):
        partition_factory(strategy=Strategy.OPTIMISTIC)
        engine.set_flaky("flake_a")
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        first_trial = _active_trial(1)

        lifecycle.on_trial_finished(first_trial.id, passed=False, failing_tests=["flake_a"])

        enrollment = Enrollment.objects.get(number=1)
        assert enrollment.state == EnrollmentState.ACTIVE
        assert not QueueEvent.objects.filter(type=QueueEventType.EJECTED).exists()
        # a fresh retry trial was launched and flagged
        retry = _active_trial(1)
        assert retry.id != first_trial.id
        assert retry.flaky_retried is True
        assert engine.launched == [first_trial.id, retry.id]


class TestBackOfLine:
    def test_reenroll_after_eject_lands_behind_waiting_pr(self, engine, partition_factory):
        partition_factory(strategy=Strategy.OPTIMISTIC)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        api.enroll(_pr(2, "b" * 40), actor=ACTOR)

        # eject #1, then re-enroll it
        lifecycle.on_trial_finished(_active_trial(1).id, passed=False, failing_tests=["real"])
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)

        status1 = api.status(_pr(1, "a" * 40))
        status2 = api.status(_pr(2, "b" * 40))
        assert status1 is not None and status2 is not None
        pos1 = status1.slots[0].position
        pos2 = status2.slots[0].position
        assert pos2 < pos1  # the re-enrolled PR is now behind the one that kept waiting


class TestSerialOrdering:
    def test_serial_holds_successor_until_predecessor_green_then_folds_it(self, engine, partition_factory):
        partition_factory(strategy=Strategy.SERIAL)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        api.enroll(_pr(2, "b" * 40), actor=ACTOR)

        # only the head trials; the successor is held (serial = one predecessor at a time)
        assert _active_trial(1).projected_head_shas == []
        assert Slot.objects.get(enrollment__number=2).state == SlotState.ENROLLED
        assert len(engine.launched) == 1

        # head passes → it merges and the successor starts, folding the predecessor head
        lifecycle.on_trial_finished(_active_trial(1).id, passed=True)

        assert Enrollment.objects.get(number=1).state == EnrollmentState.MERGED
        successor_trial = _active_trial(2)
        assert successor_trial.projected_head_shas == ["a" * 40]
        assert successor_trial.projected_base_sha == "m" * 40


class TestMergeGate:
    def _spanning_enrollment(self, partition_factory) -> Enrollment:
        p1 = partition_factory(name="p1")
        p2 = partition_factory(name="p2")
        enrollment = Enrollment.objects.create(
            repo="PostHog/posthog",
            number=9,
            head_sha="c" * 40,
            state=EnrollmentState.ACTIVE,
            approval_ref="",
            enrolled_by_id="7",
            enrolled_by_kind="human",
        )
        now = timezone.now()
        Slot.objects.create(enrollment=enrollment, partition=p1, state=SlotState.GREEN, enqueued_at=now)
        Slot.objects.create(enrollment=enrollment, partition=p2, state=SlotState.TRIALING, enqueued_at=now)
        return enrollment

    def test_does_not_merge_until_every_slot_is_green(self, engine, partition_factory):
        enrollment = self._spanning_enrollment(partition_factory)
        slot = enrollment.slots.first()
        assert slot is not None
        partition = slot.partition

        lifecycle.advance(partition)
        assert Enrollment.objects.get(number=9).state == EnrollmentState.ACTIVE  # one slot still trialing

        enrollment.slots.filter(state=SlotState.TRIALING).update(state=SlotState.GREEN)
        lifecycle.advance(partition)
        assert Enrollment.objects.get(number=9).state == EnrollmentState.MERGED


class TestConcurrentMergeGuard:
    def test_stale_driver_loses_the_merge_claim(self, engine, partition_factory):
        partition = partition_factory(strategy=Strategy.OPTIMISTIC)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        trial = _active_trial(1)

        # a second concurrent driver holding a stale ACTIVE handle, as two trial
        # completions landing at once would
        stale = Enrollment.objects.get(number=1)
        assert stale.state == EnrollmentState.ACTIVE

        lifecycle.on_trial_finished(trial.id, passed=True)  # first driver merges
        lifecycle.merge_enrollment(stale, partition)  # second driver's ACTIVE→MERGED claim finds no row

        assert QueueEvent.objects.filter(type=QueueEventType.MERGED).count() == 1


class TestFreeze:
    def test_frozen_partition_does_not_merge_a_finishing_trial(self, engine, partition_factory):
        partition_factory(name="default", strategy=Strategy.OPTIMISTIC)
        api.enroll(_pr(1, "a" * 40), actor=ACTOR)
        trial = _active_trial(1)

        api.freeze(Scope.of("default"), actor=ACTOR)

        # the in-flight trial finishes and records GREEN, but the freeze keeps advance inert
        lifecycle.on_trial_finished(trial.id, passed=True)
        assert Slot.objects.get().state == SlotState.GREEN
        assert Enrollment.objects.get(number=1).state == EnrollmentState.ACTIVE
        assert not QueueEvent.objects.filter(type=QueueEventType.MERGED).exists()

        # unfreeze resumes from the persisted GREEN result and merges
        api.unfreeze(Scope.of("default"), actor=ACTOR)
        assert Enrollment.objects.get(number=1).state == EnrollmentState.MERGED
        assert QueueEvent.objects.filter(type=QueueEventType.MERGED).count() == 1


class TestProjectedState:
    def test_optimistic_projects_master_head_only(self, partition_factory):
        partition = partition_factory(strategy=Strategy.OPTIMISTIC)
        enrollment = Enrollment.objects.create(
            repo="r",
            number=1,
            head_sha="a" * 40,
            state=EnrollmentState.ACTIVE,
            approval_ref="",
            enrolled_by_id="7",
            enrolled_by_kind="human",
        )
        slot = Slot.objects.create(
            enrollment=enrollment, partition=partition, state=SlotState.ENROLLED, enqueued_at=timezone.now()
        )
        projected = projected_state.build(slot, Strategy.OPTIMISTIC, master_head_sha="m" * 40)
        assert projected.base_sha == "m" * 40
        assert projected.predecessor_shas == []
