import re
import datetime
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from confluent_kafka import (
    TIMESTAMP_CREATE_TIME,
    TIMESTAMP_NOT_AVAILABLE,
    Consumer,
    KafkaError,
    KafkaException,
    Message,
    TopicPartition,
)
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    HostNotAllowedError,
    HostResolution,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kafka import KafkaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.kafka import (
    AUTHENTICATION_FAILED_MESSAGE,
    KAFKA_CLOUD_UNAVAILABLE_MESSAGE,
    MISSING_SASL_CREDENTIALS_MESSAGE,
    UNREACHABLE_MESSAGE,
    KafkaCluster,
    KafkaCursor,
    KafkaSourceError,
    build_client_config,
    fetch_cluster,
    kafka_source,
    message_to_row,
    parse_bootstrap_hosts,
    read_partitions,
    resolve_start_offsets,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kafka.kafka"
_EOF = KafkaError._PARTITION_EOF  # type: ignore[attr-defined]


class _FakeMessage:
    def __init__(
        self,
        partition: int,
        offset: int,
        value: bytes | None = b"{}",
        key: bytes | None = None,
        headers: list[tuple[str, bytes | None]] | None = None,
        timestamp: tuple[int, int] = (TIMESTAMP_CREATE_TIME, 1_700_000_000_000),
        error: KafkaError | None = None,
    ) -> None:
        self._partition = partition
        self._offset = offset
        self._value = value
        self._key = key
        self._headers = headers
        self._timestamp = timestamp
        self._error = error

    def topic(self) -> str:
        return "orders"

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes | None:
        return self._value

    def key(self) -> bytes | None:
        return self._key

    def headers(self) -> list[tuple[str, bytes | None]] | None:
        return self._headers

    def timestamp(self) -> tuple[int, int]:
        return self._timestamp

    def error(self) -> KafkaError | None:
        return self._error


class _FakeConsumer:
    def __init__(
        self, batches: list[list[_FakeMessage]], positions: dict[int, int] | None = None, may_idle: bool = False
    ) -> None:
        self._batches = list(batches)
        self._positions = positions or {}
        self._may_idle = may_idle
        self.assigned: list[tuple[int, int]] | None = None

    def assign(self, partitions: list[TopicPartition]) -> None:
        self.assigned = [(tp.partition, tp.offset) for tp in partitions]

    def consume(self, num_messages: int, timeout: float) -> list[_FakeMessage]:
        if self._batches:
            return self._batches.pop(0)
        # A read that should have finished must not wait for more messages.
        assert self._may_idle, "read past the last message"
        return []

    def position(self, partitions: list[TopicPartition]) -> list[TopicPartition]:
        return [TopicPartition(tp.topic, tp.partition, self._positions.get(tp.partition, -1001)) for tp in partitions]


def _read(
    consumer: _FakeConsumer, starts: dict[int, int], ends: dict[int, int]
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    progress: list[dict[int, int]] = []
    rows = [
        row
        for batch in read_partitions(
            cast(Consumer, consumer),
            "orders",
            starts,
            ends,
            "json",
            lambda offsets: progress.append(dict(offsets)),
            MagicMock(),
        )
        for row in batch
    ]
    return rows, progress[-1]


def _config(**overrides: Any) -> KafkaSourceConfig:
    return KafkaSourceConfig.from_dict(
        {
            "bootstrap_servers": "broker.example.com:9092",
            "authentication": {"selection": "sasl_plain", "username": "key", "password": "secret"},
            **overrides,
        }
    )


class TestResolveStartOffsets:
    @parameterized.expand(
        [
            ("no_cursor_starts_at_the_first_retained_message", None, (10, 50), 10),
            ("cursor_inside_the_log", {"0": 30}, (10, 50), 30),
            ("cursor_at_the_end_reads_nothing", {"0": 50}, (10, 50), 50),
            ("retention_deleted_past_the_cursor", {"0": 5}, (10, 50), 10),
            ("topic_recreated_behind_the_cursor", {"0": 900}, (0, 40), 0),
            ("partition_added_since_the_last_run", {"1": 30}, (10, 50), 10),
        ]
    )
    def test_start_offset(
        self, _name: str, stored: dict[str, int] | None, watermarks: tuple[int, int], expected: int
    ) -> None:
        assert resolve_start_offsets(stored, {0: watermarks}, MagicMock()) == {0: expected}


class TestMessageToRow:
    @parameterized.expand(
        [
            ("json_object_becomes_columns", "json", b'{"id": 1, "name": "a"}', {"id": 1, "name": "a"}),
            ("json_non_object_is_kept_as_json_text", "json", b"[1, 2]", {"value": "[1,2]"}),
            ("json_string_is_kept_as_json_text", "json", b'"hi"', {"value": '"hi"'}),
            ("invalid_json_is_kept_raw", "json", b"not json {", {"_kafka_raw_value": "not json {"}),
            ("text_is_kept_whole", "text", b'{"id": 1}', {"value": '{"id": 1}'}),
            ("tombstone_has_no_payload", "json", None, {}),
        ]
    )
    def test_payload(self, _name: str, value_format: Any, value: bytes | None, expected_payload: dict) -> None:
        row = message_to_row(cast(Message, _FakeMessage(0, 7, value=value)), value_format)
        envelope = {key: row.pop(key) for key in list(row) if key.startswith("_kafka_") and key != "_kafka_raw_value"}
        assert row == expected_payload
        assert envelope["_kafka_tombstone"] is (value is None)

    def test_reserved_and_invalid_payload_fields_are_namespaced(self) -> None:
        message = _FakeMessage(
            2,
            7,
            value=b'{"_kafka_offset": 99, "_ph_debug": "payload", "not valid!": true, "ok": 1}',
        )
        row = message_to_row(cast(Message, message), "json")
        assert (row["_kafka_partition"], row["_kafka_offset"]) == (2, 7)
        assert row["ok"] == 1
        assert "_ph_debug" not in row
        assert any(key.startswith("_kafka_payload_not_validx_") for key in row)
        assert len([key for key in row if key.startswith("_kafka_payload_")]) == 3

    def test_envelope(self) -> None:
        message = _FakeMessage(1, 3, key=b"user-1", headers=[("trace", b"abc"), ("empty", None)])
        row = message_to_row(cast(Message, message), "json")
        assert row["_kafka_key"] == "user-1"
        assert row["_kafka_headers"] == '[["trace","abc"],["empty",null]]'
        assert row["_kafka_timestamp"] == datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.UTC)

    def test_message_without_a_timestamp(self) -> None:
        message = _FakeMessage(0, 0, timestamp=(TIMESTAMP_NOT_AVAILABLE, -1))
        row = message_to_row(cast(Message, message), "json")
        assert row["_kafka_timestamp"] is None
        assert row["_kafka_timestamp_ms"] is None

    def test_out_of_range_timestamp_keeps_raw_milliseconds(self) -> None:
        timestamp_ms = 2**63 - 1
        message = _FakeMessage(0, 0, timestamp=(TIMESTAMP_CREATE_TIME, timestamp_ms))
        row = message_to_row(cast(Message, message), "json")
        assert row["_kafka_timestamp"] is None
        assert row["_kafka_timestamp_ms"] == timestamp_ms

    def test_binary_key_headers_and_raw_value_are_base64_encoded(self) -> None:
        message = _FakeMessage(0, 0, value=b"\xff", key=b"\xfe", headers=[("binary", b"\xfd")])
        row = message_to_row(cast(Message, message), "json")
        assert row["_kafka_raw_value"] == "/w=="
        assert row["_kafka_raw_value_encoding"] == "base64"
        assert row["_kafka_key"] == "/g=="
        assert row["_kafka_key_encoding"] == "base64"
        assert row["_kafka_headers"] == '[["binary",{"data":"/Q==","encoding":"base64"}]]'


class TestReadPartitions:
    def test_stops_at_the_end_offsets_captured_at_the_start(self) -> None:
        consumer = _FakeConsumer(
            [
                [_FakeMessage(0, 3), _FakeMessage(1, 0), _FakeMessage(0, 4)],
                # Written after the run captured its end offsets.
                [_FakeMessage(0, 5), _FakeMessage(1, 1)],
            ]
        )
        rows, cursor = _read(consumer, starts={0: 3, 1: 0}, ends={0: 5, 1: 1})
        assert consumer.assigned == [(0, 3), (1, 0)]
        assert [(row["_kafka_partition"], row["_kafka_offset"]) for row in rows] == [(0, 3), (1, 0), (0, 4)]
        assert cursor == {0: 5, 1: 1}

    def test_a_partition_that_ends_in_transaction_markers_finishes_at_its_position(self) -> None:
        # The markers at offsets 1 and 2 are never delivered, so only the position shows the end.
        consumer = _FakeConsumer([[_FakeMessage(0, 0)]], positions={0: 3})
        rows, cursor = _read(consumer, starts={0: 0}, ends={0: 3})
        assert len(rows) == 1
        assert cursor == {0: 3}

    def test_end_of_partition_finishes_it(self) -> None:
        eof = _FakeMessage(0, 2, error=KafkaError(_EOF))
        rows, cursor = _read(_FakeConsumer([[_FakeMessage(0, 0), eof]]), starts={0: 0}, ends={0: 2})
        assert len(rows) == 1
        assert cursor == {0: 2}

    def test_a_stalled_partition_stops_at_its_position(self) -> None:
        # An open transaction holds back what a read_committed consumer can see.
        consumer = _FakeConsumer([[_FakeMessage(0, 0)]], positions={0: 1}, may_idle=True)
        with patch(f"{_MODULE}.IDLE_TIMEOUT_SECONDS", -1):
            rows, cursor = _read(consumer, starts={0: 0}, ends={0: 10})
        assert len(rows) == 1
        assert cursor == {0: 1}

    def test_nothing_to_read_reports_the_start_offsets_without_assigning(self) -> None:
        consumer = _FakeConsumer([])
        rows, cursor = _read(consumer, starts={0: 7}, ends={0: 7})
        assert (rows, cursor, consumer.assigned) == ([], {0: 7}, None)

    def test_a_message_error_fails_the_read(self) -> None:
        broken = _FakeMessage(0, 0, error=KafkaError(KafkaError.TOPIC_AUTHORIZATION_FAILED))  # type: ignore[attr-defined]
        with pytest.raises(KafkaException):
            _read(_FakeConsumer([[broken]]), starts={0: 0}, ends={0: 5})


class TestKafkaSourceSetup:
    @staticmethod
    def _topic_metadata(error: KafkaError | None = None) -> MagicMock:
        return MagicMock(error=error, partitions={0: MagicMock()})

    @staticmethod
    def _topic_description(topic_id: str = "topic-id") -> MagicMock:
        future = MagicMock()
        future.result.return_value = MagicMock(topic_id=topic_id)
        return MagicMock(describe_topics=MagicMock(return_value={"orders": future}))

    def test_consumer_reads_only_committed_records(self) -> None:
        consumer = MagicMock()
        consumer.list_topics.return_value = MagicMock(topics={"orders": self._topic_metadata()})
        consumer.get_watermark_offsets.return_value = (0, 0)
        cursor = MagicMock()
        cursor.load.return_value = None
        with (
            patch(f"{_MODULE}.fetch_cluster", return_value=KafkaCluster(topics=["orders"])),
            patch(f"{_MODULE}.Consumer", return_value=consumer) as consumer_class,
            patch(f"{_MODULE}.AdminClient", return_value=self._topic_description()),
        ):
            response = kafka_source(_config(), "orders", 1, cursor, True, MagicMock())

        assert consumer_class.call_args.args[0]["isolation.level"] == "read_committed"
        assert list(cast(Iterable[Any], response.items())) == []
        consumer.close.assert_called_once()

    def test_topic_metadata_error_closes_the_consumer(self) -> None:
        consumer = MagicMock()
        consumer.list_topics.return_value = MagicMock(
            topics={"orders": self._topic_metadata(KafkaError(KafkaError.UNKNOWN_TOPIC_OR_PART))}  # type: ignore[attr-defined]
        )
        with (
            patch(f"{_MODULE}.fetch_cluster", return_value=KafkaCluster(topics=["orders"])),
            patch(f"{_MODULE}.Consumer", return_value=consumer),
            patch(f"{_MODULE}.AdminClient") as admin,
            pytest.raises(KafkaSourceError, match=re.escape("topic for this table no longer exists")),
        ):
            kafka_source(_config(), "orders", 1, MagicMock(), True, MagicMock())

        consumer.close.assert_called_once()
        admin.assert_not_called()

    def test_changed_topic_identity_rebuilds_from_the_low_watermark(self) -> None:
        consumer = MagicMock()
        consumer.list_topics.return_value = MagicMock(topics={"orders": self._topic_metadata()})
        consumer.get_watermark_offsets.return_value = (3, 5)
        cursor = MagicMock()
        cursor.load.return_value = KafkaCursor(offsets={"0": 100}, topic_id="old-topic-id")
        with (
            patch(f"{_MODULE}.fetch_cluster", return_value=KafkaCluster(topics=["orders"])),
            patch(f"{_MODULE}.Consumer", return_value=consumer),
            patch(f"{_MODULE}.AdminClient", return_value=self._topic_description("new-topic-id")),
        ):
            response = kafka_source(_config(), "orders", 1, cursor, True, MagicMock())

        assert response.destination_reset_required is True
        assert response.rows_to_sync == 2


class TestClientConfig:
    @parameterized.expand(
        [
            ("sasl_plain", "tls", "SASL_SSL", "PLAIN"),
            ("sasl_scram_sha_512", "tls", "SASL_SSL", "SCRAM-SHA-512"),
            ("sasl_scram_sha_256", "none", "SASL_PLAINTEXT", "SCRAM-SHA-256"),
            ("none", "tls", "SSL", None),
            ("none", "none", "PLAINTEXT", None),
        ]
    )
    def test_security_protocol(self, selection: str, encryption: str, protocol: str, mechanism: str | None) -> None:
        config = _config(
            authentication={"selection": selection, "username": "key", "password": "secret"}, encryption=encryption
        )
        client_config = build_client_config(config, MagicMock())
        assert client_config["security.protocol"] == protocol
        assert client_config.get("sasl.mechanism") == mechanism

    def test_ca_certificate_is_passed_as_pem(self) -> None:
        client_config = build_client_config(_config(ca_certificate="-----BEGIN CERTIFICATE-----"), MagicMock())
        assert client_config["ssl.ca.pem"] == "-----BEGIN CERTIFICATE-----"

    def test_sasl_without_credentials_is_rejected(self) -> None:
        with pytest.raises(KafkaSourceError, match=re.escape(MISSING_SASL_CREDENTIALS_MESSAGE)):
            build_client_config(_config(authentication={"selection": "sasl_plain"}), MagicMock())


@parameterized.expand(
    [
        ("host_and_port_list", "a.example.com:9092, b.example.com:9093", ["a.example.com", "b.example.com"]),
        ("listener_scheme", "SASL_SSL://a.example.com:9092", ["a.example.com"]),
        ("ipv6", "[2001:db8::1]:9092", ["2001:db8::1"]),
        ("no_port", "a.example.com", ["a.example.com"]),
        ("trailing_comma", "a.example.com:9092,", ["a.example.com"]),
    ]
)
def test_parse_bootstrap_hosts(_name: str, servers: str, expected: list[str]) -> None:
    assert parse_bootstrap_hosts(servers) == expected


class TestFetchCluster:
    @staticmethod
    def _metadata(topics: dict[str, Any], broker_hosts: list[str]) -> MagicMock:
        return MagicMock(
            topics={name: MagicMock(error=error) for name, error in topics.items()},
            brokers={index: MagicMock(host=host) for index, host in enumerate(broker_hosts)},
        )

    @staticmethod
    def _resolve(private_hosts: set[str]) -> Any:
        def resolve(host: str, team_id: int) -> HostResolution:
            if host in private_hosts:
                return HostResolution(connect_host=None, error="This host points to an internal or private IP address")
            return HostResolution(connect_host=host, error=None)

        return resolve

    def test_lists_readable_topics_without_internal_ones(self) -> None:
        metadata = self._metadata(
            {"orders": None, "__consumer_offsets": None, "_schemas": None, "broken": KafkaError(3), "clicks": None},
            ["broker.example.com"],
        )
        with (
            patch(f"{_MODULE}.AdminClient") as admin,
            patch(f"{_MODULE}.resolve_safe_host", side_effect=self._resolve(set())),
        ):
            admin.return_value.list_topics.return_value = metadata
            assert fetch_cluster(_config(), team_id=1).topics == ["clicks", "orders"]

    def test_a_private_advertised_broker_is_rejected(self) -> None:
        # The bootstrap host is public, but the metadata it returns points the client at a private address.
        metadata = self._metadata({"orders": None}, ["10.0.0.5"])
        with (
            patch(f"{_MODULE}.AdminClient") as admin,
            patch(f"{_MODULE}.resolve_safe_host", side_effect=self._resolve({"10.0.0.5"})),
        ):
            admin.return_value.list_topics.return_value = metadata
            with pytest.raises(HostNotAllowedError):
                fetch_cluster(_config(), team_id=1)

    def test_cloud_teams_are_rejected_before_connecting(self) -> None:
        with (
            patch(f"{_MODULE}.is_cloud", return_value=True),
            patch(f"{_MODULE}.is_team_allowlisted_for_internal_hosts", return_value=False),
            patch(f"{_MODULE}.AdminClient") as admin,
        ):
            with pytest.raises(HostNotAllowedError, match=re.escape(KAFKA_CLOUD_UNAVAILABLE_MESSAGE)):
                fetch_cluster(_config(), team_id=1)
        admin.assert_not_called()

    def test_a_private_bootstrap_host_is_rejected_before_connecting(self) -> None:
        with (
            patch(f"{_MODULE}.AdminClient") as admin,
            patch(f"{_MODULE}.resolve_safe_host", side_effect=self._resolve({"broker.example.com"})),
        ):
            with pytest.raises(HostNotAllowedError):
                fetch_cluster(_config(), team_id=1)
        admin.assert_not_called()

    @parameterized.expand(
        [
            ("authentication_failure", KafkaError._AUTHENTICATION, AUTHENTICATION_FAILED_MESSAGE),  # type: ignore[attr-defined]
            ("unreachable_brokers", KafkaError._TRANSPORT, UNREACHABLE_MESSAGE),  # type: ignore[attr-defined]
        ]
    )
    def test_a_failed_metadata_request_is_named_by_the_client_errors(
        self, _name: str, reported_code: int, expected_message: str
    ) -> None:
        def admin_client(client_config: dict[str, Any]) -> MagicMock:
            def list_topics(timeout: float) -> None:
                client_config["error_cb"](KafkaError(reported_code))
                raise KafkaException(KafkaError(KafkaError._TIMED_OUT))  # type: ignore[attr-defined]

            return MagicMock(list_topics=list_topics)

        with (
            patch(f"{_MODULE}.AdminClient", side_effect=admin_client),
            patch(f"{_MODULE}.resolve_safe_host", side_effect=self._resolve(set())),
        ):
            with pytest.raises(KafkaSourceError, match=re.escape(expected_message)):
                fetch_cluster(_config(), team_id=1)
