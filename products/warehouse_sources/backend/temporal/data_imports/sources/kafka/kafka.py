import time
import base64
import hashlib
import logging
import datetime
from collections.abc import Callable, Iterator, Mapping
from typing import Any, ClassVar, Literal

import orjson
from confluent_kafka import (
    TIMESTAMP_NOT_AVAILABLE,
    Consumer,
    KafkaError,
    KafkaException,
    Message,
    TopicCollection,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient
from structlog.types import FilteringBoundLogger

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    DATABASE_HOST_NOT_ALLOWED_ERROR,
    HostNotAllowedError,
    is_team_allowlisted_for_internal_hosts,
    resolve_safe_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kafka import KafkaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.settings import (
    CLIENT_ID,
    CONSUME_BATCH_SIZE,
    CONSUME_TIMEOUT_SECONDS,
    HEADERS_COLUMN,
    IDLE_TIMEOUT_SECONDS,
    INTERNAL_TOPIC_PREFIX,
    KEY_COLUMN,
    KEY_ENCODING_COLUMN,
    METADATA_TIMEOUT_SECONDS,
    OFFSET_COLUMN,
    PARTITION_COLUMN,
    PRIMARY_KEYS,
    RAW_VALUE_COLUMN,
    RAW_VALUE_ENCODING_COLUMN,
    TIMESTAMP_COLUMN,
    TIMESTAMP_MS_COLUMN,
    TOMBSTONE_COLUMN,
    TOPIC_COLUMN,
    VALUE_COLUMN,
    VALUE_ENCODING_COLUMN,
    WATERMARK_TIMEOUT_SECONDS,
)

AUTHENTICATION_FAILED_MESSAGE = (
    "Kafka rejected the username or password. Check the credentials and the SASL mechanism, then try again."
)
MISSING_SASL_CREDENTIALS_MESSAGE = "Enter a username and password, or choose no authentication."
TLS_FAILED_MESSAGE = (
    "PostHog could not open a TLS connection to your Kafka brokers. Check that the brokers accept TLS "
    "on these ports, and add your CA certificate if a public certificate authority did not sign theirs."
)
UNREACHABLE_MESSAGE = (
    "PostHog could not connect to your Kafka brokers. Check the bootstrap servers, and that the brokers "
    "accept connections from the internet."
)
NO_TOPICS_MESSAGE = (
    "PostHog connected to Kafka but found no topics. Check that this user has permission to describe "
    "and read the topics you want to import."
)
TOPIC_NOT_FOUND_MESSAGE = "The Kafka topic for this table no longer exists, or this user can no longer read it."
KAFKA_CLOUD_UNAVAILABLE_MESSAGE = (
    "Kafka sources are not available on PostHog Cloud because the Kafka client cannot pin broker DNS addresses."
)

_SASL_MECHANISMS: dict[str, str] = {
    "sasl_plain": "PLAIN",
    "sasl_scram_sha_256": "SCRAM-SHA-256",
    "sasl_scram_sha_512": "SCRAM-SHA-512",
}

# The client's type stubs leave out librdkafka's error code constants.
_PARTITION_EOF: int = KafkaError._PARTITION_EOF  # type: ignore[attr-defined]
# librdkafka reports these through `error_cb` while `list_topics` only reports a timeout, so the
# callback's errors are what name the cause.
_AUTHENTICATION_ERROR_CODES: set[int] = {
    KafkaError._AUTHENTICATION,  # type: ignore[attr-defined]
    KafkaError.SASL_AUTHENTICATION_FAILED,  # type: ignore[attr-defined]
}
_TLS_ERROR_CODES: set[int] = {KafkaError._SSL}  # type: ignore[attr-defined]


class KafkaSourceError(Exception):
    """A failure with a message that is safe and useful to show the user."""


@frozen
class KafkaCursor:
    """The next offset to read in each partition of one topic, keyed by partition number.

    Partition numbers are strings because the cursor is stored as JSON, whose object keys are strings.
    """

    cursor_kind: ClassVar[str] = "kafka_offsets"

    offsets: dict[str, int]
    topic_id: str | None = None


@frozen
class KafkaCluster:
    topics: list[str]


class _ErrorCollector:
    def __init__(self) -> None:
        self.errors: list[KafkaError] = []

    def __call__(self, error: KafkaError) -> None:
        self.errors.append(error)

    def user_error(self) -> KafkaSourceError:
        codes = {error.code() for error in self.errors}
        if codes & _AUTHENTICATION_ERROR_CODES:
            return KafkaSourceError(AUTHENTICATION_FAILED_MESSAGE)
        if codes & _TLS_ERROR_CODES:
            return KafkaSourceError(TLS_FAILED_MESSAGE)
        return KafkaSourceError(UNREACHABLE_MESSAGE)


def parse_bootstrap_hosts(bootstrap_servers: str) -> list[str]:
    hosts = []
    for server in bootstrap_servers.split(","):
        address = server.strip().split("://")[-1]
        if not address:
            continue
        if address.startswith("["):
            hosts.append(address[1 : address.index("]")])
        else:
            hosts.append(address.rsplit(":", 1)[0] if address.count(":") == 1 else address)
    return hosts


def build_client_config(config: KafkaSourceConfig, error_cb: Callable[[KafkaError], None]) -> dict[str, Any]:
    authentication = config.authentication
    uses_sasl = authentication.selection != "none"
    uses_tls = config.encryption == "tls"
    client_config: dict[str, Any] = {
        "bootstrap.servers": config.bootstrap_servers,
        "security.protocol": f"{'SASL_' if uses_sasl else ''}{'SSL' if uses_tls else 'PLAINTEXT'}",
        "client.id": CLIENT_ID,
        "error_cb": error_cb,
        "logger": logging.getLogger(__name__),
    }
    if uses_sasl:
        if not authentication.username or not authentication.password:
            raise KafkaSourceError(MISSING_SASL_CREDENTIALS_MESSAGE)
        client_config["sasl.mechanism"] = _SASL_MECHANISMS[authentication.selection]
        client_config["sasl.username"] = authentication.username
        client_config["sasl.password"] = authentication.password
    if uses_tls and config.ca_certificate:
        client_config["ssl.ca.pem"] = config.ca_certificate
    return client_config


def _check_hosts(hosts: list[str], team_id: int) -> None:
    for host in hosts:
        resolution = resolve_safe_host(host, team_id)
        if resolution.connect_host is None:
            raise HostNotAllowedError(f"{DATABASE_HOST_NOT_ALLOWED_ERROR}: {resolution.error}")


def fetch_cluster(config: KafkaSourceConfig, team_id: int) -> KafkaCluster:
    """List the importable topics, after checking every broker the client talks to is a public host.

    The bootstrap servers only hand out the cluster's metadata. The client then connects to each
    broker the metadata advertises, so those addresses are checked as well as the configured ones.
    """
    if is_cloud() and not is_team_allowlisted_for_internal_hosts(team_id):
        # librdkafka resolves broker names itself and exposes no resolver hook. A separate preflight
        # lookup would leave a DNS-rebinding gap, so untrusted Cloud teams cannot use this raw socket.
        raise HostNotAllowedError(KAFKA_CLOUD_UNAVAILABLE_MESSAGE)

    _check_hosts(parse_bootstrap_hosts(config.bootstrap_servers), team_id)

    errors = _ErrorCollector()
    admin = AdminClient(build_client_config(config, errors))
    try:
        metadata = admin.list_topics(timeout=METADATA_TIMEOUT_SECONDS)
    except KafkaException as e:
        raise errors.user_error() from e

    # The client's metadata types leave `host` unannotated, and it is always set on a returned broker.
    _check_hosts([str(broker.host) for broker in metadata.brokers.values()], team_id)
    topics = sorted(
        name
        for name, topic in metadata.topics.items()
        if not name.startswith(INTERNAL_TOPIC_PREFIX) and topic.error is None
    )
    return KafkaCluster(topics=topics)


def resolve_start_offsets(
    stored: Mapping[str, int] | None,
    watermarks: Mapping[int, tuple[int, int]],
    logger: FilteringBoundLogger,
) -> dict[int, int]:
    """The offset each partition starts from, given the cursor and each partition's (low, high) watermarks.

    A partition the cursor does not know, such as one added to the topic since the last run, starts at
    its first retained message. Starting it at the end would skip what was written before this run.
    """
    starts: dict[int, int] = {}
    for partition, (low, high) in watermarks.items():
        stored_offset = stored.get(str(partition)) if stored is not None else None
        if stored_offset is None:
            starts[partition] = low
        elif stored_offset < low:
            logger.warning(
                "Kafka retention deleted messages this table never read",
                partition=partition,
                stored_offset=stored_offset,
                low_watermark=low,
            )
            starts[partition] = low
        elif stored_offset > high:
            # The log is shorter than the cursor, so the topic was deleted and created again.
            logger.warning(
                "Kafka partition is behind the stored cursor, reading it again from the start",
                partition=partition,
                stored_offset=stored_offset,
                high_watermark=high,
            )
            starts[partition] = low
        else:
            starts[partition] = stored_offset
    return starts


_RESERVED_PAYLOAD_COLUMNS = frozenset(
    {
        TOPIC_COLUMN,
        PARTITION_COLUMN,
        OFFSET_COLUMN,
        TIMESTAMP_COLUMN,
        TIMESTAMP_MS_COLUMN,
        KEY_COLUMN,
        KEY_ENCODING_COLUMN,
        HEADERS_COLUMN,
        TOMBSTONE_COLUMN,
        RAW_VALUE_COLUMN,
        RAW_VALUE_ENCODING_COLUMN,
        VALUE_COLUMN,
        VALUE_ENCODING_COLUMN,
        "_ph_debug",
        "_ph_partition_key",
        "_dlt_id",
        "_dlt_load_id",
    }
)


@frozen
class _DecodedValue:
    value: str | None
    encoding: str | None


def _decode_losslessly(data: bytes | str | None) -> _DecodedValue:
    if data is None:
        return _DecodedValue(value=None, encoding=None)
    if isinstance(data, str):
        return _DecodedValue(value=data, encoding="utf-8")
    try:
        return _DecodedValue(value=data.decode("utf-8"), encoding="utf-8")
    except UnicodeDecodeError:
        return _DecodedValue(value=base64.b64encode(data).decode("ascii"), encoding="base64")


def _payload_column_name(name: str) -> str:
    try:
        normalized = NamingConvention.normalize_identifier(name)
    except ValueError:
        normalized = "column"
    if name == normalized and normalized not in _RESERVED_PAYLOAD_COLUMNS and not normalized.startswith("_kafka_"):
        return normalized
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"_kafka_payload_{normalized}_{digest}"


def _timestamp(timestamp_type: int, timestamp_ms: int) -> datetime.datetime | None:
    if timestamp_type == TIMESTAMP_NOT_AVAILABLE:
        return None
    try:
        return datetime.datetime.fromtimestamp(timestamp_ms / 1000, tz=datetime.UTC)
    except (ValueError, OverflowError, OSError):
        return None


def message_to_row(message: Message, value_format: Literal["json", "text"]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    value = message.value()
    if value is not None:
        if value_format == "text":
            decoded_value = _decode_losslessly(value)
            row[VALUE_COLUMN], row[VALUE_ENCODING_COLUMN] = decoded_value.value, decoded_value.encoding
        else:
            try:
                decoded = orjson.loads(value)
            except orjson.JSONDecodeError:
                decoded_value = _decode_losslessly(value)
                row[RAW_VALUE_COLUMN], row[RAW_VALUE_ENCODING_COLUMN] = decoded_value.value, decoded_value.encoding
            else:
                if isinstance(decoded, dict):
                    row.update({_payload_column_name(key): item for key, item in decoded.items()})
                else:
                    # Stored as JSON text, so a topic that mixes numbers and strings keeps one column type.
                    row[VALUE_COLUMN] = orjson.dumps(decoded).decode()

    timestamp_type, timestamp_ms = message.timestamp()
    decoded_key = _decode_losslessly(message.key())
    headers = message.headers()
    encoded_headers = []
    for name, data in headers.items() if isinstance(headers, dict) else headers or []:
        decoded_header = _decode_losslessly(data)
        encoded_headers.append(
            [name, {"data": decoded_header.value, "encoding": decoded_header.encoding}]
            if decoded_header.encoding == "base64"
            else [name, decoded_header.value]
        )

    row.update(
        {
            TOPIC_COLUMN: message.topic(),
            PARTITION_COLUMN: message.partition(),
            OFFSET_COLUMN: message.offset(),
            TIMESTAMP_COLUMN: _timestamp(timestamp_type, timestamp_ms),
            TIMESTAMP_MS_COLUMN: None if timestamp_type == TIMESTAMP_NOT_AVAILABLE else timestamp_ms,
            KEY_COLUMN: decoded_key.value,
            KEY_ENCODING_COLUMN: decoded_key.encoding,
            HEADERS_COLUMN: orjson.dumps(encoded_headers).decode() if headers else None,
            TOMBSTONE_COLUMN: value is None,
        }
    )
    return row


def read_partitions(
    consumer: Consumer,
    topic: str,
    starts: Mapping[int, int],
    ends: Mapping[int, int],
    value_format: Literal["json", "text"],
    on_progress: Callable[[dict[int, int]], None],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the messages of each partition from its start offset up to, not including, its end offset.

    `on_progress` receives the next offset to read in every partition after each batch, so it never
    names an offset past a row that has not been yielded.
    """
    next_offsets = dict(starts)
    remaining = {partition for partition in starts if starts[partition] < ends[partition]}
    if not remaining:
        on_progress(next_offsets)
        return

    consumer.assign([TopicPartition(topic, partition, starts[partition]) for partition in remaining])
    last_delivery = time.monotonic()
    while remaining:
        rows: list[dict[str, Any]] = []
        for message in consumer.consume(num_messages=CONSUME_BATCH_SIZE, timeout=CONSUME_TIMEOUT_SECONDS):
            partition = message.partition()
            offset = message.offset()
            error = message.error()
            if error is not None and error.code() != _PARTITION_EOF:
                raise KafkaException(error)
            if partition is None or offset is None or partition not in remaining:
                continue
            if error is not None:
                next_offsets[partition] = max(next_offsets[partition], min(offset, ends[partition]))
                remaining.discard(partition)
                continue
            if offset >= ends[partition]:
                # Written after this run captured its end offsets. The next run reads it.
                remaining.discard(partition)
                continue
            rows.append(message_to_row(message, value_format))
            next_offsets[partition] = offset + 1
            if next_offsets[partition] >= ends[partition]:
                remaining.discard(partition)

        # A read_committed consumer skips transaction markers and aborted messages without delivering
        # them, so a partition can pass its end offset with no message at the end to say so.
        if remaining:
            for position in consumer.position([TopicPartition(topic, partition) for partition in remaining]):
                if position.offset >= 0:
                    next_offsets[position.partition] = max(
                        next_offsets[position.partition], min(position.offset, ends[position.partition])
                    )
                if next_offsets[position.partition] >= ends[position.partition]:
                    remaining.discard(position.partition)

        if rows:
            last_delivery = time.monotonic()
            yield rows
        elif remaining and time.monotonic() - last_delivery > IDLE_TIMEOUT_SECONDS:
            logger.warning(
                "Kafka partitions stopped short of their end offsets, the next sync continues them",
                partitions=sorted(remaining),
            )
            remaining.clear()
        on_progress(next_offsets)


def kafka_source(
    config: KafkaSourceConfig,
    topic: str,
    team_id: int,
    cursor: SourceCursorManager[KafkaCursor],
    resume: bool,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Read the topic from the stored cursor, or from the start when `resume` is false."""
    cluster = fetch_cluster(config, team_id)
    if topic not in cluster.topics:
        raise KafkaSourceError(TOPIC_NOT_FOUND_MESSAGE)

    errors = _ErrorCollector()
    client_config = build_client_config(config, errors)
    consumer = Consumer(
        {
            **client_config,
            # Required by the client, though the source assigns partitions itself and never joins or
            # commits to the group, so a customer's own consumer groups are never touched.
            "group.id": f"{CLIENT_ID}-{team_id}",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "enable.partition.eof": True,
            "isolation.level": "read_committed",
        }
    )
    try:
        topic_metadata = consumer.list_topics(topic, timeout=METADATA_TIMEOUT_SECONDS).topics[topic]
        if topic_metadata.error is not None:
            raise KafkaSourceError(TOPIC_NOT_FOUND_MESSAGE)
        try:
            topic_description = (
                AdminClient(client_config)
                .describe_topics(TopicCollection([topic]), request_timeout=METADATA_TIMEOUT_SECONDS)[topic]
                .result(timeout=METADATA_TIMEOUT_SECONDS)
            )
        except KafkaException as e:
            raise KafkaSourceError(TOPIC_NOT_FOUND_MESSAGE) from e
        topic_id = str(topic_description.topic_id)
        watermarks = {
            partition: consumer.get_watermark_offsets(
                TopicPartition(topic, partition), timeout=WATERMARK_TIMEOUT_SECONDS, cached=False
            )
            for partition in topic_metadata.partitions
        }
    except Exception as e:
        consumer.close()
        if isinstance(e, KafkaException):
            raise errors.user_error() from e
        raise

    try:
        stored = cursor.load()
        topic_recreated = False
        if resume and stored is not None and stored.topic_id and stored.topic_id != topic_id:
            topic_recreated = True
            logger.warning(
                "Kafka topic identity changed, rebuilding the destination from the new topic",
                old_topic_id=stored.topic_id,
                new_topic_id=topic_id,
            )
        stored_offsets = stored.offsets if resume and stored is not None and not topic_recreated else None
        starts = resolve_start_offsets(stored_offsets, watermarks, logger)
        ends = {partition: high for partition, (_, high) in watermarks.items()}
    except Exception:
        consumer.close()
        raise

    def on_progress(next_offsets: dict[int, int]) -> None:
        cursor.stage(
            KafkaCursor(
                offsets={str(partition): offset for partition, offset in next_offsets.items()}, topic_id=topic_id
            )
        )

    def items() -> Iterator[list[dict[str, Any]]]:
        try:
            yield from read_partitions(consumer, topic, starts, ends, config.value_format, on_progress, logger)
        finally:
            consumer.close()

    return SourceResponse(
        name=topic,
        items=items,
        primary_keys=PRIMARY_KEYS,
        partition_mode="datetime",
        partition_keys=[TIMESTAMP_COLUMN],
        # Messages arrive ordered by offset within a partition, not by timestamp across partitions.
        sort_mode="desc",
        rows_to_sync=sum(ends[partition] - starts[partition] for partition in starts),
        destination_reset_required=topic_recreated,
    )
