import pytest

from products.merge_queue.backend.facade import api
from products.merge_queue.backend.facade.types import Actor, ActorKind, PRRef, Scope
from products.merge_queue.backend.models import Enrollment, EnrollmentState, Partition, QueueEvent, QueueEventType

pytestmark = pytest.mark.django_db

HUMAN = Actor(id="7", kind=ActorKind.HUMAN, display="Ada")
AGENT = Actor(id="bot-1", kind=ActorKind.AGENT, display="posthog-code")


def _pr(number: int = 42) -> PRRef:
    return PRRef(repo="PostHog/posthog", number=number, head_sha="a" * 40)


class TestEnroll:
    def test_enroll_creates_enrollment_slot_and_event(self, engine, partition_factory):
        partition_factory()
        status = api.enroll(_pr(), actor=HUMAN)

        assert status.state == EnrollmentState.ACTIVE
        assert len(status.slots) == 1
        assert status.slots[0].position == 0
        assert Enrollment.objects.filter(repo="PostHog/posthog", number=42, state="active").count() == 1
        assert QueueEvent.objects.filter(type=QueueEventType.ENROLLED).count() == 1

    def test_double_enroll_raises_already_enrolled(self, engine, partition_factory):
        partition_factory()
        api.enroll(_pr(), actor=HUMAN)
        with pytest.raises(api.AlreadyEnrolled):
            api.enroll(_pr(), actor=HUMAN)

    def test_enroll_without_partition_raises(self, engine):
        with pytest.raises(api.NoMatchingPartition):
            api.enroll(_pr(), actor=HUMAN)


class TestStatusAndDequeue:
    def test_status_none_when_not_enrolled(self):
        assert api.status(_pr()) is None

    def test_dequeue_marks_dequeued_and_emits(self, engine, partition_factory):
        partition_factory()
        api.enroll(_pr(), actor=HUMAN)
        api.dequeue(_pr(), actor=HUMAN, reason="superseded")

        assert api.status(_pr()) is None
        assert Enrollment.objects.get(number=42).state == EnrollmentState.DEQUEUED
        event = QueueEvent.objects.get(type=QueueEventType.DEQUEUED)
        assert event.payload == {"reason": "superseded"}

    def test_dequeue_unenrolled_raises(self, partition_factory):
        partition_factory()
        with pytest.raises(api.NotEnrolled):
            api.dequeue(_pr(), actor=HUMAN, reason="x")


class TestBreakGlass:
    def test_break_glass_human_merges_and_audits(self, engine, partition_factory):
        partition_factory()
        api.enroll(_pr(), actor=HUMAN)
        api.break_glass(_pr(), actor=HUMAN)

        assert Enrollment.objects.get(number=42).state == EnrollmentState.MERGED
        assert QueueEvent.objects.filter(type=QueueEventType.BREAK_GLASS_USED).count() == 1

    @pytest.mark.parametrize("actor", [AGENT, Actor(id="cowboy", kind=ActorKind.COWBOY)])
    def test_break_glass_rejects_non_human(self, engine, partition_factory, actor):
        partition_factory()
        api.enroll(_pr(), actor=HUMAN)
        with pytest.raises(api.NotHumanActor):
            api.break_glass(_pr(), actor=actor)
        # no merge, no audit event
        assert Enrollment.objects.get(number=42).state == EnrollmentState.ACTIVE
        assert not QueueEvent.objects.filter(type=QueueEventType.BREAK_GLASS_USED).exists()


class TestFreeze:
    def test_freeze_and_unfreeze_partition(self, partition_factory):
        partition_factory(name="frontend")
        api.freeze(Scope.of("frontend"), actor=HUMAN)
        assert Partition.objects.get(name="frontend").is_frozen
        assert QueueEvent.objects.filter(type=QueueEventType.FROZEN).count() == 1

        api.unfreeze(Scope.of("frontend"), actor=HUMAN)
        assert not Partition.objects.get(name="frontend").is_frozen
        assert QueueEvent.objects.filter(type=QueueEventType.UNFROZEN).count() == 1

    def test_freeze_whole_queue_covers_all_partitions(self, partition_factory):
        partition_factory(name="a")
        partition_factory(name="b")
        api.freeze(Scope.queue(), actor=HUMAN)
        assert all(p.is_frozen for p in Partition.objects.all())
