import pytest

from products.merge_queue.backend import observability
from products.merge_queue.backend.facade.decisions import StrategyDecision
from products.merge_queue.backend.facade.types import Actor, ActorKind
from products.merge_queue.backend.models import Partition, QueueEvent, QueueEventType, Strategy


class TestEmit:
    @pytest.mark.django_db
    def test_emit_writes_exactly_one_event_with_fks_and_actor(self):
        partition = Partition.objects.create(name="default", predicate="approved")
        actor = Actor(id="123", kind=ActorKind.HUMAN, display="Ada")

        event = observability.emit(
            QueueEventType.FROZEN, actor=actor, partition=partition, payload={"reason": "deploy"}
        )

        assert QueueEvent.objects.count() == 1
        assert event.type == QueueEventType.FROZEN
        assert event.partition_id == partition.id
        assert event.actor_id == "123"
        assert event.actor_kind == "human"
        assert event.payload == {"reason": "deploy"}

    @pytest.mark.django_db
    def test_emit_without_actor_leaves_actor_columns_null(self):
        event = observability.emit(QueueEventType.ENROLLED)
        assert event.actor_id is None
        assert event.actor_kind is None


class TestSerialize:
    def test_serialize_unpacks_nested_dataclasses(self):
        decision = StrategyDecision(Strategy.SERIAL, None, 4, "pinned/default")
        assert observability._serialize(decision) == {
            "strategy": Strategy.SERIAL,
            "speculation_depth": None,
            "max_batch_size": 4,
            "reason": "pinned/default",
        }

    def test_serialize_stringifies_unknown_types(self):
        assert observability._serialize(object()).startswith("<object")
