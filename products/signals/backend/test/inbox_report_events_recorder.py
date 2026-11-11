import json
from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from posthog.kafka_client.client import KafkaProducerForTests
from posthog.kafka_client.topics import KAFKA_CDP_INTERNAL_EVENTS


@contextmanager
def recorded_internal_events(*, flag_enabled: bool | None = True) -> Iterator[tuple[list[dict], MagicMock]]:
    sent: list[dict] = []
    original_produce = KafkaProducerForTests.produce

    def record(self, topic, value, key=None, headers=None, on_delivery=None):
        if topic == KAFKA_CDP_INTERNAL_EVENTS:
            sent.append(json.loads(value))
        return original_produce(self, topic, value, key=key, headers=headers, on_delivery=on_delivery)

    with (
        patch.object(KafkaProducerForTests, "produce", record),
        patch("posthoganalytics.disabled", False),
        patch("products.signals.backend.inbox_report_events.feature_enabled", return_value=flag_enabled) as flag,
    ):
        yield sent, flag


def inbox_report_ready_events(sent: list[dict]) -> list[dict]:
    return [message["event"]["properties"] for message in sent if message["event"]["event"] == "$inbox_report_ready"]
