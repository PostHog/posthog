"""Replay exception events from the raw error tracking ingestion topic.

The ingestion pipeline drops an exception that a suppression rule matches, and it keeps no copy.
Until retention removes it, the only copy is the message capture produced to the ingestion topic.
This module reads a time window of that topic and produces the matching messages back to it, so
that they go through the pipeline again under the current rules.
"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, cast

from confluent_kafka import Consumer, Producer, TopicPartition

from posthog.dataclasses import frozen
from posthog.settings.kafka import KafkaProfileSettings

Header = tuple[str, bytes | str | None]
Classification = Literal["replay", "skip", "unparseable"]

EXCEPTION_EVENT = "$exception"


@frozen
class ReplayWindow:
    """The Kafka message timestamps to replay: start is inclusive, end is exclusive."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("The replay window needs timezone-aware timestamps.")
        if self.start >= self.end:
            raise ValueError("The replay window start must be before its end.")


@frozen
class ReplayCriteria:
    """Which exception events to replay: one project token, and event properties that must all match."""

    token: str
    properties: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("The replay criteria need a project token.")
        if not self.properties:
            # A window of one project's exceptions also holds the events that were ingested
            # normally. Without a property filter the replay would duplicate all of them.
            raise ValueError("The replay criteria need at least one property filter.")


@frozen
class PartitionRange:
    """The offsets to read on one partition: start_offset is inclusive, end_offset is exclusive."""

    partition: int
    start_offset: int
    end_offset: int


@frozen
class ReplayResult:
    scanned: int
    replayed: int
    unparseable: int
    errors: int
    complete: bool


def default_group_id(*, window: ReplayWindow, criteria: ReplayCriteria) -> str:
    """Return a consumer group id that is unique to this window and these criteria.

    The group's committed offsets are how an interrupted run resumes. A group shared between two
    different replays would make the second one start from the offsets of the first.
    """
    fingerprint = json.dumps(
        [window.start.isoformat(), window.end.isoformat(), criteria.token, sorted(criteria.properties.items())]
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"error-tracking-suppressed-exception-replay-{digest}"


def _header_value(headers: Sequence[Header] | None, name: str) -> str | None:
    for key, raw in headers or []:
        if key != name:
            continue
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return raw
    return None


def classify_message(headers: Sequence[Header] | None, value: bytes | None, criteria: ReplayCriteria) -> Classification:
    """Decide whether to replay one message of the ingestion topic.

    The headers that capture sets are checked first, because they reject the messages of every
    other project without a JSON parse of the payload.
    """
    header_token = _header_value(headers, "token")
    if header_token is not None and header_token != criteria.token:
        return "skip"
    header_event = _header_value(headers, "event")
    if header_event is not None and header_event != EXCEPTION_EVENT:
        return "skip"

    try:
        envelope = json.loads(value or b"")
        if envelope["token"] != criteria.token:
            return "skip"
        # Capture serializes the event twice: `data` is a JSON string inside the envelope.
        event = json.loads(envelope["data"])
        if event["event"] != EXCEPTION_EVENT:
            return "skip"
        properties = event.get("properties") or {}
        matches = all(properties.get(key) == expected for key, expected in criteria.properties.items())
    except (ValueError, KeyError, TypeError, AttributeError):
        # Only report a payload we know belongs to the project. A broken message of an unknown
        # project is not this replay's concern.
        return "unparseable" if header_token == criteria.token else "skip"
    return "replay" if matches else "skip"


def plan_partition_ranges(
    *,
    start_offsets: Mapping[int, int | None],
    end_offsets: Mapping[int, int | None],
    high_watermarks: Mapping[int, int],
    committed_offsets: Mapping[int, int | None],
) -> list[PartitionRange]:
    """Turn the per-partition offset lookups into the ranges left to read.

    start_offsets and end_offsets hold the first offset at or after the window start and end; None
    means the partition has no message that late. committed_offsets holds the progress of an
    earlier run of the same consumer group.
    """
    ranges: list[PartitionRange] = []
    for partition in sorted(start_offsets):
        start_offset = start_offsets[partition]
        if start_offset is None:
            continue
        end_offset = end_offsets.get(partition)
        if end_offset is None:
            # The window ends after the newest message. The high watermark, read before the first
            # produce, keeps the replay from reading the messages it writes to this topic.
            end_offset = high_watermarks[partition]
        committed_offset = committed_offsets.get(partition)
        if committed_offset is not None:
            start_offset = max(start_offset, committed_offset)
        if start_offset < end_offset:
            ranges.append(PartitionRange(partition=partition, start_offset=start_offset, end_offset=end_offset))
    return ranges


def _client_config(
    profile: KafkaProfileSettings, bootstrap_servers: str | None, security_protocol: str | None
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "bootstrap.servers": bootstrap_servers or ",".join(profile.hosts),
        "security.protocol": security_protocol or profile.security_protocol or "PLAINTEXT",
    }
    if profile.sasl_mechanism:
        config["sasl.mechanism"] = profile.sasl_mechanism
        if profile.sasl_user:
            config["sasl.username"] = profile.sasl_user
        if profile.sasl_password:
            config["sasl.password"] = profile.sasl_password
    return config


def build_replay_consumer(
    *,
    profile: KafkaProfileSettings,
    group_id: str,
    bootstrap_servers: str | None = None,
    security_protocol: str | None = None,
) -> Consumer:
    return Consumer(
        {
            **_client_config(profile, bootstrap_servers, security_protocol),
            "group.id": group_id,
            "enable.auto.commit": False,
            # The replay assigns explicit offsets. If retention removed one of them, a reset would
            # move the consumer to another offset and the run would skip messages without a trace.
            "auto.offset.reset": "error",
        }
    )


def build_replay_producer(
    *,
    profile: KafkaProfileSettings,
    bootstrap_servers: str | None = None,
    security_protocol: str | None = None,
    max_message_bytes: int | None = None,
) -> Producer:
    config: dict[str, Any] = {**_client_config(profile, bootstrap_servers, security_protocol), "acks": "all"}
    # A replayed record is as large as capture allowed, so the producer must accept that size or
    # the run stops on the first large exception.
    message_max_bytes = max_message_bytes or profile.producer_settings.get("max_request_size")
    if message_max_bytes:
        config["message.max.bytes"] = int(message_max_bytes)
    return Producer(config)


class SuppressedExceptionReplayer:
    """Reads a window of the ingestion topic and produces the matching messages back to it.

    Without a producer the replayer counts the matching messages, and it produces and commits
    nothing.
    """

    def __init__(
        self,
        *,
        consumer: Consumer,
        producer: Producer | None,
        topic: str,
        criteria: ReplayCriteria,
        batch_size: int = 500,
        poll_timeout_seconds: float = 10.0,
        idle_polls: int = 6,
        request_timeout_seconds: float = 30.0,
        should_stop: Callable[[], bool] = lambda: False,
        log: Callable[[str], None] = print,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._topic = topic
        self._criteria = criteria
        self._batch_size = batch_size
        self._poll_timeout_seconds = poll_timeout_seconds
        self._idle_polls = idle_polls
        self._request_timeout_seconds = request_timeout_seconds
        self._should_stop = should_stop
        self._log = log

    def plan(self, window: ReplayWindow) -> list[PartitionRange]:
        """Resolve the window to offset ranges, one for each partition that has messages left to read."""
        topic_metadata = self._consumer.list_topics(self._topic, timeout=self._request_timeout_seconds).topics.get(
            self._topic
        )
        if topic_metadata is None or topic_metadata.error is not None or not topic_metadata.partitions:
            raise ValueError(f"Topic {self._topic} was not found on this cluster.")
        partitions = sorted(topic_metadata.partitions)

        committed = self._consumer.committed(
            [TopicPartition(self._topic, partition) for partition in partitions],
            timeout=self._request_timeout_seconds,
        )
        return plan_partition_ranges(
            start_offsets=self._offsets_at(partitions, window.start),
            end_offsets=self._offsets_at(partitions, window.end),
            high_watermarks={
                partition: self._consumer.get_watermark_offsets(
                    TopicPartition(self._topic, partition), timeout=self._request_timeout_seconds
                )[1]
                for partition in partitions
            },
            committed_offsets={entry.partition: _valid_offset(entry.offset) for entry in committed},
        )

    def run(self, ranges: Sequence[PartitionRange]) -> ReplayResult:
        remaining = {partition_range.partition: partition_range for partition_range in ranges}
        scanned = replayed = unparseable = errors = 0
        # confluent-kafka reports a rejected record through the delivery callback, not through
        # produce() or flush(). Without this list the run would commit past records the broker
        # never took.
        delivery_failures: list[str] = []

        def on_delivery(err: Any, _message: Any) -> None:
            if err is not None:
                delivery_failures.append(str(err))

        self._consumer.assign(
            [
                TopicPartition(self._topic, partition_range.partition, partition_range.start_offset)
                for partition_range in ranges
            ]
        )
        idle = 0
        while remaining:
            if self._should_stop():
                self._log("stop requested; exiting after the last committed batch")
                break
            messages = self._consumer.consume(num_messages=self._batch_size, timeout=self._poll_timeout_seconds)
            if not messages:
                idle += 1
                if idle >= self._idle_polls:
                    self._log(f"no messages after {idle} polls with {len(remaining)} partition(s) unfinished")
                    break
                continue
            idle = 0

            delivery_failures.clear()
            produced = 0
            next_offsets: dict[int, int] = {}
            finished: list[TopicPartition] = []
            for message in messages:
                consume_error = message.error()
                if consume_error is not None:
                    errors += 1
                    self._log(f"consume error: {consume_error}")
                    continue
                partition = cast(int, message.partition())
                offset = cast(int, message.offset())
                partition_range = remaining.get(partition)
                if partition_range is None:
                    continue
                if offset < partition_range.end_offset:
                    scanned += 1
                    next_offsets[partition] = offset + 1
                    headers = cast("Sequence[Header] | None", message.headers())
                    value = cast("bytes | None", message.value())
                    classification = classify_message(headers, value, self._criteria)
                    if classification == "unparseable":
                        unparseable += 1
                    elif classification == "replay":
                        if self._producer is None:
                            replayed += 1
                        else:
                            self._produce(cast("bytes | None", message.key()), value, headers, on_delivery)
                            produced += 1
                if offset + 1 >= partition_range.end_offset:
                    del remaining[partition]
                    finished.append(TopicPartition(self._topic, partition))
            if finished:
                self._consumer.pause(finished)

            if self._producer is not None:
                self._producer.flush()
                failed = len(delivery_failures)
                replayed += produced - failed
                errors += failed
                if failed:
                    self._log(f"delivery failed for {failed} record(s); stopping: {delivery_failures[0]}")
                    return ReplayResult(
                        scanned=scanned, replayed=replayed, unparseable=unparseable, errors=errors, complete=False
                    )
                if next_offsets:
                    self._consumer.commit(
                        offsets=[
                            TopicPartition(self._topic, partition, offset) for partition, offset in next_offsets.items()
                        ],
                        asynchronous=False,
                    )
            self._log(
                f"progress: scanned={scanned} replayed={replayed} unparseable={unparseable} "
                f"errors={errors} partitions_left={len(remaining)}"
            )

        return ReplayResult(
            scanned=scanned, replayed=replayed, unparseable=unparseable, errors=errors, complete=not remaining
        )

    def _offsets_at(self, partitions: Sequence[int], moment: datetime) -> dict[int, int | None]:
        timestamp_ms = int(moment.timestamp() * 1000)
        resolved = self._consumer.offsets_for_times(
            [TopicPartition(self._topic, partition, timestamp_ms) for partition in partitions],
            timeout=self._request_timeout_seconds,
        )
        return {entry.partition: _valid_offset(entry.offset) for entry in resolved}

    def _produce(
        self,
        key: bytes | None,
        value: bytes | None,
        headers: Sequence[Header] | None,
        on_delivery: Callable[[Any, Any], None],
    ) -> None:
        producer = cast(Producer, self._producer)
        while True:
            try:
                # The record carries no timestamp, so it gets the current time. That places it
                # after the end of the window, where a second run of the same window cannot
                # read it.
                producer.produce(
                    topic=self._topic,
                    key=key,
                    value=value,
                    headers=cast(Any, list(headers)) if headers else None,
                    on_delivery=on_delivery,
                )
                return
            except BufferError:
                # The local produce queue is full. Let it drain, then retry the same message.
                producer.poll(1.0)


def _valid_offset(offset: int) -> int | None:
    # librdkafka reports "no offset" with negative sentinels: OFFSET_END for a timestamp past the
    # newest message, OFFSET_INVALID for a group that has no commit.
    return offset if offset >= 0 else None
