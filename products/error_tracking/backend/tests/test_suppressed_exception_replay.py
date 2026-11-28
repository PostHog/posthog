import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from unittest import TestCase

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from confluent_kafka import TIMESTAMP_CREATE_TIME, Consumer, KafkaError, KafkaException, Producer, TopicPartition
from parameterized import parameterized

from products.error_tracking.backend.logic.suppressed_exception_replay import (
    Header,
    PartitionRange,
    ReplayCriteria,
    ReplayWindow,
    SuppressedExceptionReplayer,
    classify_message,
    parse_partition_spec,
    plan_partition_ranges,
    select_partitions,
)

TOPIC = "ingestion-errortracking-main_test"
TOKEN = "phc_replayed_project"
CRITERIA = ReplayCriteria(token=TOKEN, properties={"service": "checkout"})
WINDOW = ReplayWindow(start=datetime(2026, 1, 10, 9, tzinfo=UTC), end=datetime(2026, 1, 10, 10, tzinfo=UTC))
WINDOW_START_MS = int(WINDOW.start.timestamp() * 1000)
WINDOW_END_MS = int(WINDOW.end.timestamp() * 1000)
BROKER_ERROR = KafkaError(KafkaError._TIMED_OUT)  # type: ignore[attr-defined]


def _payload(*, token: str = TOKEN, event: str = "$exception", properties: dict[str, Any] | None = None) -> bytes:
    data = {"event": event, "properties": {"service": "checkout"} if properties is None else properties}
    return json.dumps(
        {"uuid": "0190f0f0-0000-7000-8000-000000000000", "token": token, "data": json.dumps(data)}
    ).encode()


def _headers(*, token: str = TOKEN, event: str = "$exception") -> list[Header]:
    return [("token", token.encode()), ("event", event.encode())]


class ClassifyMessageTest(TestCase):
    @parameterized.expand(
        [
            ("matching_exception", _headers(), _payload(), "replay"),
            ("matching_exception_without_headers", None, _payload(), "replay"),
            ("other_project_in_headers", _headers(token="phc_other"), _payload(token="phc_other"), "skip"),
            ("other_project_without_headers", None, _payload(token="phc_other"), "skip"),
            ("other_event_in_headers", _headers(event="$pageview"), _payload(event="$pageview"), "skip"),
            ("other_event_without_headers", None, _payload(event="$pageview"), "skip"),
            ("property_has_other_value", _headers(), _payload(properties={"service": "search"}), "skip"),
            ("property_is_missing", _headers(), _payload(properties={}), "skip"),
            ("broken_payload_of_the_project", _headers(), b"{not json", "unparseable"),
            ("broken_payload_of_unknown_project", None, b"{not json", "skip"),
        ]
    )
    def test_classifies(self, _name: str, headers: list[Header] | None, value: bytes, expected: str) -> None:
        assert classify_message(headers, value, CRITERIA) == expected

    def test_requires_every_property_to_match(self) -> None:
        criteria = ReplayCriteria(token=TOKEN, properties={"service": "checkout", "environment": "production"})

        only_one = _payload(properties={"service": "checkout", "environment": "dev"})
        both = _payload(properties={"service": "checkout", "environment": "production"})

        assert classify_message(_headers(), only_one, criteria) == "skip"
        assert classify_message(_headers(), both, criteria) == "replay"


class SelectPartitionsTest(TestCase):
    @parameterized.expand(
        [
            ("single_partition", "7", {7}),
            ("range_includes_both_ends", "0-3", {0, 1, 2, 3}),
            ("list_of_ranges_and_numbers", "0-1, 5,126-127", {0, 1, 5, 126, 127}),
        ]
    )
    def test_parses_partition_spec(self, _name: str, raw: str, expected: set[int]) -> None:
        assert parse_partition_spec(raw) == expected

    @parameterized.expand([("not_a_number", "a"), ("reversed_range", "5-2"), ("empty_item", "1,,2")])
    def test_rejects_malformed_partition_spec(self, _name: str, raw: str) -> None:
        with self.assertRaises(ValueError):
            parse_partition_spec(raw)

    def test_selects_requested_partitions_and_rejects_unknown_ones(self) -> None:
        assert select_partitions([2, 0, 1], None) == [0, 1, 2]
        assert select_partitions([2, 0, 1], frozenset({2, 0})) == [0, 2]
        with self.assertRaises(ValueError):
            select_partitions([0, 1, 2], frozenset({2, 3}))


class PlanPartitionRangesTest(TestCase):
    @parameterized.expand(
        [
            ("window_inside_the_partition", 10, 20, 50, None, [(0, 10, 20)]),
            ("window_ends_after_newest_message", 10, None, 50, None, [(0, 10, 50)]),
            ("no_message_after_window_start", None, None, 50, None, []),
            ("resumes_from_committed_offset", 10, 20, 50, 15, [(0, 15, 20)]),
            ("ignores_commit_before_window", 10, 20, 50, 4, [(0, 10, 20)]),
            ("skips_partition_already_replayed", 10, 20, 50, 20, []),
            ("skips_empty_window", 10, 10, 50, None, []),
        ]
    )
    def test_plans(
        self,
        _name: str,
        start: int | None,
        end: int | None,
        high_watermark: int,
        committed: int | None,
        expected: list[tuple[int, int, int]],
    ) -> None:
        ranges = plan_partition_ranges(
            start_offsets={0: start},
            end_offsets={0: end},
            high_watermarks={0: high_watermark},
            committed_offsets={0: committed},
        )

        assert [(r.partition, r.start_offset, r.end_offset) for r in ranges] == expected


class FakeMessage:
    def __init__(
        self,
        partition: int,
        offset: int,
        value: bytes,
        headers: list[Header] | None = None,
        timestamp_ms: int = WINDOW_START_MS,
    ) -> None:
        self._partition = partition
        self._offset = offset
        self._value = value
        self._headers = headers
        self._timestamp_ms = timestamp_ms

    def timestamp(self) -> tuple[int, int]:
        return (TIMESTAMP_CREATE_TIME, self._timestamp_ms)

    def error(self) -> None:
        return None

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def key(self) -> bytes:
        return f"key-{self._partition}-{self._offset}".encode()

    def value(self) -> bytes:
        return self._value

    def headers(self) -> list[Header] | None:
        return self._headers


class FakeConsumer:
    """Serves each partition's log from the assigned offset, and keeps serving past any end offset."""

    def __init__(
        self, logs: dict[int, list[FakeMessage]], fail_commit: bool = False, fail_offset_lookup: bool = False
    ) -> None:
        self._logs = logs
        self._fail_commit = fail_commit
        self._fail_offset_lookup = fail_offset_lookup
        self._positions: dict[int, int] = {}
        self._paused: set[int] = set()
        self.committed_offsets: dict[int, int] = {}

    def assign(self, partitions: list[TopicPartition]) -> None:
        self._positions = {tp.partition: tp.offset for tp in partitions}

    def consume(self, num_messages: int, timeout: float) -> list[FakeMessage]:
        batch: list[FakeMessage] = []
        for partition, position in self._positions.items():
            if partition in self._paused:
                continue
            for message in self._logs[partition]:
                if message.offset() >= position and len(batch) < num_messages:
                    batch.append(message)
                    self._positions[partition] = message.offset() + 1
        return batch

    def pause(self, partitions: list[TopicPartition]) -> None:
        self._paused.update(tp.partition for tp in partitions)

    def commit(self, offsets: list[TopicPartition], asynchronous: bool) -> list[Any]:
        if self._fail_commit:
            return [SimpleNamespace(partition=tp.partition, error=BROKER_ERROR) for tp in offsets]
        self.committed_offsets.update({tp.partition: tp.offset for tp in offsets})
        return [SimpleNamespace(partition=tp.partition, error=None) for tp in offsets]

    def list_topics(self, topic: str, timeout: float) -> Any:
        partitions = dict.fromkeys(self._logs)
        return SimpleNamespace(topics={topic: SimpleNamespace(error=None, partitions=partitions)})

    def committed(self, partitions: list[TopicPartition], timeout: float) -> list[Any]:
        return [SimpleNamespace(partition=tp.partition, offset=-1001, error=None) for tp in partitions]

    def offsets_for_times(self, partitions: list[TopicPartition], timeout: float) -> list[Any]:
        error = BROKER_ERROR if self._fail_offset_lookup else None
        return [SimpleNamespace(partition=tp.partition, offset=-1001 if error else 0, error=error) for tp in partitions]

    def get_watermark_offsets(self, partition: TopicPartition, timeout: float) -> tuple[int, int]:
        return (0, len(self._logs[partition.partition]))


class FakeProducer:
    def __init__(self, fail_delivery: bool = False) -> None:
        self._fail_delivery = fail_delivery
        self._pending: list[Any] = []
        self.produced: list[dict[str, Any]] = []

    def produce(self, *, topic: str, key: bytes, value: bytes, headers: Any, on_delivery: Any) -> None:
        self.produced.append({"topic": topic, "key": key, "value": value, "headers": headers})
        self._pending.append(on_delivery)

    def flush(self) -> None:
        for on_delivery in self._pending:
            on_delivery("broker rejected the record" if self._fail_delivery else None, None)
        self._pending = []


def _log(partition: int, values: list[bytes]) -> list[FakeMessage]:
    return [FakeMessage(partition, offset, value, _headers()) for offset, value in enumerate(values)]


class SuppressedExceptionReplayerTest(TestCase):
    def _replayer(self, consumer: FakeConsumer, producer: FakeProducer | None) -> SuppressedExceptionReplayer:
        return SuppressedExceptionReplayer(
            consumer=cast(Consumer, consumer),
            producer=cast(Producer, producer) if producer is not None else None,
            topic=TOPIC,
            criteria=CRITERIA,
            batch_size=2,
            idle_polls=1,
            log=lambda _message: None,
        )

    def test_replays_matching_messages_inside_each_range_unchanged(self) -> None:
        other = _payload(properties={"service": "search"})
        consumer = FakeConsumer(
            {
                0: _log(0, [_payload(), other, _payload(), _payload(), _payload()]),
                1: _log(1, [_payload(), _payload(), _payload()]),
            }
        )
        producer = FakeProducer()

        result = self._replayer(consumer, producer).run(
            [
                PartitionRange(partition=0, start_offset=1, end_offset=4),
                PartitionRange(partition=1, start_offset=0, end_offset=1),
            ],
            WINDOW,
        )

        assert (result.scanned, result.replayed, result.complete) == (4, 3, True)
        assert producer.produced == [
            {"topic": TOPIC, "key": b"key-0-2", "value": _payload(), "headers": _headers()},
            {"topic": TOPIC, "key": b"key-0-3", "value": _payload(), "headers": _headers()},
            {"topic": TOPIC, "key": b"key-1-0", "value": _payload(), "headers": _headers()},
        ]
        assert consumer.committed_offsets == {0: 4, 1: 1}

    def test_stops_at_the_end_offset_when_the_log_has_an_offset_gap(self) -> None:
        consumer = FakeConsumer(
            {0: [FakeMessage(0, 0, _payload(), _headers()), FakeMessage(0, 5, _payload(), _headers())]}
        )
        producer = FakeProducer()

        result = self._replayer(consumer, producer).run(
            [PartitionRange(partition=0, start_offset=0, end_offset=3)], WINDOW
        )

        assert (result.replayed, result.complete) == (1, True)
        assert [record["key"] for record in producer.produced] == [b"key-0-0"]
        assert consumer.committed_offsets == {0: 1}

    def test_dry_run_counts_without_committing(self) -> None:
        consumer = FakeConsumer({0: _log(0, [_payload(), _payload()])})

        result = self._replayer(consumer, None).run([PartitionRange(partition=0, start_offset=0, end_offset=2)], WINDOW)

        assert (result.scanned, result.replayed, result.complete) == (2, 2, True)
        assert consumer.committed_offsets == {}

    def test_delivery_failure_stops_without_committing_the_batch(self) -> None:
        consumer = FakeConsumer({0: _log(0, [_payload(), _payload(), _payload(), _payload()])})

        result = self._replayer(consumer, FakeProducer(fail_delivery=True)).run(
            [PartitionRange(partition=0, start_offset=0, end_offset=4)], WINDOW
        )

        assert (result.replayed, result.errors, result.complete) == (0, 2, False)
        assert consumer.committed_offsets == {}

    def test_reports_an_incomplete_run_when_the_topic_stops_serving_messages(self) -> None:
        consumer = FakeConsumer({0: _log(0, [_payload()])})

        result = self._replayer(consumer, FakeProducer()).run(
            [PartitionRange(partition=0, start_offset=0, end_offset=3)], WINDOW
        )

        assert (result.replayed, result.complete) == (1, False)

    def test_skips_messages_whose_timestamp_is_outside_the_window(self) -> None:
        consumer = FakeConsumer(
            {
                0: [
                    FakeMessage(0, 0, _payload(), _headers(), timestamp_ms=WINDOW_START_MS - 1),
                    FakeMessage(0, 1, _payload(), _headers(), timestamp_ms=WINDOW_START_MS),
                    FakeMessage(0, 2, _payload(), _headers(), timestamp_ms=WINDOW_END_MS),
                ]
            }
        )
        producer = FakeProducer()

        result = self._replayer(consumer, producer).run(
            [PartitionRange(partition=0, start_offset=0, end_offset=3)], WINDOW
        )

        assert (result.out_of_window, result.replayed, result.complete) == (2, 1, True)
        assert [record["key"] for record in producer.produced] == [b"key-0-1"]

    def test_commit_failure_stops_the_run_as_incomplete(self) -> None:
        consumer = FakeConsumer({0: _log(0, [_payload(), _payload(), _payload(), _payload()])}, fail_commit=True)

        result = self._replayer(consumer, FakeProducer()).run(
            [PartitionRange(partition=0, start_offset=0, end_offset=4)], WINDOW
        )

        assert (result.replayed, result.errors, result.complete) == (2, 1, False)

    def test_plan_fails_when_an_offset_lookup_reports_a_partition_error(self) -> None:
        consumer = FakeConsumer({0: _log(0, [_payload()])}, fail_offset_lookup=True)

        with self.assertRaises(KafkaException):
            self._replayer(consumer, None).plan(WINDOW)


class ReplayCommandArgumentsTest(SimpleTestCase):
    @parameterized.expand(
        [
            ("window_ends_in_the_future", "2999-01-01T00:00:00+00:00", ["service=checkout"], "future"),
            (
                "property_given_twice",
                "2026-01-10T10:00:00+00:00",
                ["service=checkout", "service=search"],
                "more than once",
            ),
        ]
    )
    def test_rejects(self, _name: str, end: str, properties: list[str], expected_message: str) -> None:
        arguments = ["--team-id", "1", "--start", "2026-01-10T09:00:00+00:00", "--end", end]
        for property_filter in properties:
            arguments += ["--property", property_filter]

        with self.assertRaisesRegex(CommandError, expected_message):
            call_command("replay_suppressed_error_tracking_exceptions", *arguments)
