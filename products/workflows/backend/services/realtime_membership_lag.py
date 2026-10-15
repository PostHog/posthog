import time
import uuid
from typing import Any

from django.conf import settings
from django.core.cache import cache

from confluent_kafka import Consumer, TopicPartition

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.kafka_client.routing import get_profile_settings
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED

_LAG_CACHE_KEY = "workflows:realtime_cohort_membership_lag_seconds"
# Every batch run that starts within this window shares one measurement.
_LAG_CACHE_SECONDS = 30
_KAFKA_TIMEOUT_SECONDS = 10
# The batch resolver matches this code to wait for the copy to catch up. Keep it in step with
# REALTIME_MEMBERSHIP_LAGGING_CODE in nodejs/src/cdp/services/hogflows/hogflow-batch-person-query.service.ts.
REALTIME_MEMBERSHIP_LAGGING_CODE = "realtime_membership_lagging"


class RealtimeMembershipLagging(Exception):
    """The ClickHouse copy of realtime cohort membership is too far behind to send to, or its lag
    could not be measured."""

    def __init__(self, lag_seconds: float | None):
        self.lag_seconds = lag_seconds
        super().__init__(
            "Realtime cohort membership lag could not be measured"
            if lag_seconds is None
            else f"Realtime cohort membership is {lag_seconds:.0f}s behind"
        )


def _consumer(group_id: str) -> Consumer:
    profile = get_profile_settings(profile=KafkaClusterProfile.INGESTION)
    config: dict[str, Any] = {
        "bootstrap.servers": ",".join(profile.hosts),
        "group.id": group_id,
        "enable.auto.commit": False,
    }
    if profile.security_protocol:
        config["security.protocol"] = profile.security_protocol
    if profile.security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
        config["sasl.mechanism"] = profile.sasl_mechanism
        config["sasl.username"] = profile.sasl_user
        config["sasl.password"] = profile.sasl_password
    return Consumer(config)


def measure_realtime_membership_lag_seconds() -> float:
    """The age of the oldest membership change that ClickHouse has not stored yet, or 0 when it
    has stored every change.

    ClickHouse commits the offsets of its consumer group only after it writes a block, so the
    committed offset of a partition is the first change it has not stored. The group consumer
    reads those offsets without joining the group, so it never takes partitions from ClickHouse.
    """
    group_consumer = _consumer(CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP)
    reader = _consumer(f"workflows-membership-lag-{uuid.uuid4().hex[:8]}")
    try:
        metadata = group_consumer.list_topics(KAFKA_COHORT_MEMBERSHIP_CHANGED, timeout=_KAFKA_TIMEOUT_SECONDS)
        topic = metadata.topics.get(KAFKA_COHORT_MEMBERSHIP_CHANGED)
        if topic is None or topic.error is not None or not topic.partitions:
            raise RuntimeError(f"No partition metadata for {KAFKA_COHORT_MEMBERSHIP_CHANGED}")

        committed = group_consumer.committed(
            [TopicPartition(KAFKA_COHORT_MEMBERSHIP_CHANGED, partition) for partition in topic.partitions],
            timeout=_KAFKA_TIMEOUT_SECONDS,
        )

        oldest_unstored_ms: int | None = None
        for position in committed:
            low, high = group_consumer.get_watermark_offsets(
                TopicPartition(KAFKA_COHORT_MEMBERSHIP_CHANGED, position.partition), timeout=_KAFKA_TIMEOUT_SECONDS
            )
            # A partition without a committed offset has stored nothing that is still retained.
            first_unstored = position.offset if position.offset >= 0 else low
            if first_unstored >= high:
                continue

            reader.assign([TopicPartition(KAFKA_COHORT_MEMBERSHIP_CHANGED, position.partition, first_unstored)])
            messages = reader.consume(num_messages=1, timeout=_KAFKA_TIMEOUT_SECONDS)
            if not messages or messages[0].error() is not None:
                raise RuntimeError(f"Could not read partition {position.partition} at offset {first_unstored}")
            _timestamp_type, timestamp_ms = messages[0].timestamp()
            if oldest_unstored_ms is None or timestamp_ms < oldest_unstored_ms:
                oldest_unstored_ms = timestamp_ms

        if oldest_unstored_ms is None:
            return 0.0
        return max(0.0, time.time() - oldest_unstored_ms / 1000)
    finally:
        group_consumer.close()
        reader.close()


def ensure_realtime_membership_is_current() -> None:
    """Raises `RealtimeMembershipLagging` when an audience must not read realtime membership yet.

    A failed measurement also raises: sending to a membership copy of unknown age could reach
    people who left the cohort, while the batch resolver waits and asks again.
    """
    lag_seconds = cache.get(_LAG_CACHE_KEY)
    if lag_seconds is None:
        try:
            lag_seconds = measure_realtime_membership_lag_seconds()
        except Exception as error:
            capture_exception(error)
            raise RealtimeMembershipLagging(None) from error
        cache.set(_LAG_CACHE_KEY, lag_seconds, _LAG_CACHE_SECONDS)

    if lag_seconds > settings.WORKFLOWS_REALTIME_COHORT_MAX_LAG_SECONDS:
        raise RealtimeMembershipLagging(lag_seconds)
