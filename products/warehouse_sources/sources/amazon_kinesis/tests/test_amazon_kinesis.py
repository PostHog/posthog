import base64
import datetime as dt
from collections.abc import Callable
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.sources.amazon_kinesis._config import AmazonKinesisSourceConfig
from products.warehouse_sources.sources.amazon_kinesis.amazon_kinesis import (
    KinesisCursor,
    KinesisResumeState,
    record_to_row,
    validate_credentials,
)
from products.warehouse_sources.sources.amazon_kinesis.settings import (
    ARRIVAL_TIMESTAMP_COLUMN,
    INVALID_REGION_MESSAGE,
    KPL_AGGREGATION_PREFIX,
    NO_STREAMS_MESSAGE,
    RAW_DATA_COLUMN,
    RAW_DATA_ENCODING_COLUMN,
    SEQUENCE_NUMBER_COLUMN,
    SHARD_ID_COLUMN,
    STREAM_NOT_FOUND_MESSAGE,
    VALIDATION_ERROR_MESSAGES,
    VALUE_COLUMN,
)
from products.warehouse_sources.sources.amazon_kinesis.source import AmazonKinesisSource
from products.warehouse_sources.sources.sdk import SourceCursorManager
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)

RUN_START = "2026-01-01T00:00:00Z"
BEFORE_RUN = 1767222000.0
AFTER_RUN = 1767225601.0
CREATED = 1700000000.0
SHARD_0 = "shardId-000000000000"
SHARD_1 = "shardId-000000000001"
SHARD_2 = "shardId-000000000002"


def _operation(request: RecordedRequest) -> str:
    return request.headers["x-amz-target"].rsplit(".", 1)[1]


def _kinesis(answers: dict[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    queues = {operation: list(responses) for operation, responses in answers.items()}
    return lambda request: queues[_operation(request)].pop(0)


def _summary(created: float = CREATED) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "StreamDescriptionSummary": {
                "StreamName": "clicks",
                "StreamARN": "arn:aws:kinesis:us-east-1:123456789012:stream/clicks",
                "StreamStatus": "ACTIVE",
                "RetentionPeriodHours": 24,
                "StreamCreationTimestamp": created,
                "OpenShardCount": 1,
            }
        }
    )


def _shards(*shard_ids: str, next_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"Shards": [{"ShardId": shard_id} for shard_id in shard_ids]}
    if next_token is not None:
        body["NextToken"] = next_token
    return ScriptedResponse(json=body)


def _iterator(value: str) -> ScriptedResponse:
    return ScriptedResponse(json={"ShardIterator": value})


def _record(sequence: str, arrived: float, data: bytes = b'{"page": "/pricing"}') -> dict[str, Any]:
    return {
        "SequenceNumber": sequence,
        "ApproximateArrivalTimestamp": arrived,
        "Data": base64.b64encode(data).decode(),
        "PartitionKey": "visitor-1",
    }


def _records(records: list[dict[str, Any]], next_iterator: str | None, behind: int) -> ScriptedResponse:
    body: dict[str, Any] = {"Records": records, "MillisBehindLatest": behind}
    if next_iterator is not None:
        body["NextShardIterator"] = next_iterator
    return ScriptedResponse(json=body)


def _error(code: str, message: str) -> ScriptedResponse:
    return ScriptedResponse(status=400, json={"__type": code, "message": message})


def _driver() -> SourceDriver:
    return SourceDriver(
        AmazonKinesisSource(),
        AmazonKinesisSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="example-secret",
            aws_region="us-east-1",
            aws_session_token=None,
        ),
    )


def _cursor(stored: KinesisCursor | None = None) -> SourceCursorManager[KinesisCursor]:
    return SourceCursorManager(KinesisCursor, stored, AmazonKinesisSource())


def _bodies(result: DriveResult, operation: str) -> list[dict[str, Any]]:
    return [request.json() for request in result.requests if _operation(request) == operation]


@time_machine.travel(RUN_START, tick=False)
def test_reads_every_shard_up_to_the_run_start_and_stages_the_cursor() -> None:
    manager = _cursor()
    result = _driver().run(
        "clicks",
        _kinesis(
            {
                "DescribeStreamSummary": [_summary()],
                "ListShards": [_shards(SHARD_2, SHARD_0, next_token="page-2"), _shards(SHARD_1)],
                "GetShardIterator": [_iterator("it-0"), _iterator("it-1"), _iterator("it-2")],
                "GetRecords": [
                    _records([_record("100", BEFORE_RUN)], next_iterator=None, behind=0),
                    _records([_record("200", BEFORE_RUN)], next_iterator="it-1b", behind=5000),
                    _records([_record("201", BEFORE_RUN)], next_iterator="it-1c", behind=0),
                    _records(
                        [_record("300", BEFORE_RUN), _record("301", AFTER_RUN)], next_iterator="it-2b", behind=9000
                    ),
                ],
            }
        ),
        incremental_field=ARRIVAL_TIMESTAMP_COLUMN,
        source_cursor=manager,
    )

    assert result.raised is None
    assert [row[SEQUENCE_NUMBER_COLUMN] for row in result.rows] == ["100", "200", "201", "300"]
    assert [body.get("StreamName") for body in _bodies(result, "ListShards")] == ["clicks", None]
    assert [body["ShardIterator"] for body in _bodies(result, "GetRecords")] == ["it-0", "it-1", "it-1b", "it-2"]
    assert result.committed_states[0] == KinesisResumeState(
        started_at=1767225600.0, stream_created_at=CREATED, positions={SHARD_0: "100"}, finished_shards=[SHARD_0]
    )
    assert manager.staged == KinesisCursor(
        positions={SHARD_0: "100", SHARD_1: "201", SHARD_2: "300"},
        finished_shards=[SHARD_0],
        stream_created_at=CREATED,
    )


class TestStartPosition:
    @parameterized.expand(
        [
            (
                "stored_position",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[], stream_created_at=CREATED),
                True,
                None,
                [_iterator("it-0")],
                [("AFTER_SEQUENCE_NUMBER", "100")],
                False,
                {SHARD_0: "100"},
            ),
            (
                "recreated_stream",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[], stream_created_at=CREATED - 1),
                True,
                None,
                [_iterator("it-0")],
                [("TRIM_HORIZON", None)],
                True,
                {},
            ),
            (
                "full_refresh",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[], stream_created_at=CREATED),
                False,
                None,
                [_iterator("it-0")],
                [("TRIM_HORIZON", None)],
                False,
                {},
            ),
            (
                "position_past_retention",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[], stream_created_at=CREATED),
                True,
                None,
                [
                    _error(
                        "InvalidArgumentException", "StartingSequenceNumber 100 used in GetShardIterator is invalid"
                    ),
                    _iterator("it-0"),
                ],
                [("AFTER_SEQUENCE_NUMBER", "100"), ("TRIM_HORIZON", None)],
                False,
                {SHARD_0: "100"},
            ),
            (
                "expired_shard_dropped",
                KinesisCursor(positions={SHARD_0: "100", SHARD_1: "5"}, finished_shards=[], stream_created_at=CREATED),
                True,
                None,
                [_iterator("it-0")],
                [("AFTER_SEQUENCE_NUMBER", "100")],
                False,
                {SHARD_0: "100"},
            ),
            (
                "finished_shard_skipped",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[SHARD_0], stream_created_at=CREATED),
                True,
                None,
                [],
                [],
                False,
                {SHARD_0: "100"},
            ),
            (
                "resumed_attempt",
                KinesisCursor(positions={SHARD_0: "100"}, finished_shards=[], stream_created_at=CREATED - 1),
                True,
                KinesisResumeState(
                    started_at=1767225000.0, stream_created_at=CREATED, positions={SHARD_0: "150"}, finished_shards=[]
                ),
                [_iterator("it-0")],
                [("AFTER_SEQUENCE_NUMBER", "150")],
                False,
                {SHARD_0: "150"},
            ),
        ]
    )
    @time_machine.travel(RUN_START, tick=False)
    def test_start_position(
        self,
        _name: str,
        stored: KinesisCursor,
        incremental: bool,
        resume_state: KinesisResumeState | None,
        iterator_answers: list[ScriptedResponse],
        expected_iterators: list[tuple[str, str | None]],
        expected_reset: bool,
        expected_positions: dict[str, str],
    ) -> None:
        manager = _cursor(stored)
        result = _driver().run(
            "clicks",
            _kinesis(
                {
                    "DescribeStreamSummary": [_summary()],
                    "ListShards": [_shards(SHARD_0)],
                    "GetShardIterator": iterator_answers,
                    "GetRecords": [_records([], next_iterator="it-0b", behind=0)],
                }
            ),
            resume_state=resume_state,
            incremental_field=ARRIVAL_TIMESTAMP_COLUMN,
            should_use_incremental_field=incremental,
            source_cursor=manager,
        )

        assert result.raised is None
        assert [
            (body["ShardIteratorType"], body.get("StartingSequenceNumber"))
            for body in _bodies(result, "GetShardIterator")
        ] == expected_iterators
        assert result.response is not None and result.response.destination_reset_required is expected_reset
        assert manager.staged is not None and manager.staged.positions == expected_positions


@time_machine.travel(RUN_START, tick=False)
def test_retries_a_throttled_read_and_replaces_an_expired_iterator() -> None:
    result = _driver().run(
        "clicks",
        _kinesis(
            {
                "DescribeStreamSummary": [_summary()],
                "ListShards": [_shards(SHARD_0)],
                "GetShardIterator": [_iterator("it-0"), _iterator("it-0-renewed")],
                "GetRecords": [
                    _error("ProvisionedThroughputExceededException", "Rate exceeded for shard shardId-000000000000"),
                    _records([_record("100", BEFORE_RUN)], next_iterator="it-0b", behind=4000),
                    _error("ExpiredIteratorException", "Iterator expired."),
                    _records([_record("101", BEFORE_RUN)], next_iterator="it-0c", behind=0),
                ],
            }
        ),
        incremental_field=ARRIVAL_TIMESTAMP_COLUMN,
        source_cursor=_cursor(),
    )

    assert result.raised is None
    assert [row[SEQUENCE_NUMBER_COLUMN] for row in result.rows] == ["100", "101"]
    assert _bodies(result, "GetShardIterator")[1]["StartingSequenceNumber"] == "100"
    assert [body["ShardIterator"] for body in _bodies(result, "GetRecords")] == [
        "it-0",
        "it-0",
        "it-0b",
        "it-0-renewed",
    ]


class TestRecordToRow:
    @parameterized.expand(
        [
            (
                "json_object",
                b'{"page": "/pricing", "value": 3, "_kinesis_shard_id": "spoofed"}',
                {
                    "page": "/pricing",
                    SHARD_ID_COLUMN: SHARD_0,
                    ARRIVAL_TIMESTAMP_COLUMN: dt.datetime(2025, 12, 31, 23, tzinfo=dt.UTC),
                },
                [VALUE_COLUMN, RAW_DATA_COLUMN],
            ),
            ("json_array", b"[1, 2]", {VALUE_COLUMN: "[1,2]"}, [RAW_DATA_COLUMN]),
            ("text", b"plain text", {RAW_DATA_COLUMN: "plain text", RAW_DATA_ENCODING_COLUMN: "utf-8"}, []),
            ("binary", b"\xff\xfe", {RAW_DATA_COLUMN: "//4=", RAW_DATA_ENCODING_COLUMN: "base64"}, []),
            (
                "kpl_aggregate",
                KPL_AGGREGATION_PREFIX + b'{"page": "/pricing"}',
                {
                    RAW_DATA_COLUMN: base64.b64encode(KPL_AGGREGATION_PREFIX + b'{"page": "/pricing"}').decode(),
                    RAW_DATA_ENCODING_COLUMN: "base64",
                },
                ["page"],
            ),
        ]
    )
    def test_record_to_row(self, _name: str, data: bytes, expected: dict[str, Any], absent: list[str]) -> None:
        row = record_to_row(
            {
                "SequenceNumber": "100",
                "ApproximateArrivalTimestamp": dt.datetime.fromtimestamp(BEFORE_RUN, dt.UTC),
                "Data": data,
                "PartitionKey": "visitor-1",
            },
            SHARD_0,
        )

        assert {key: row.get(key) for key in expected} == expected
        assert not set(absent) & set(row)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("host_in_region", "us-east-1.example.com", None, [], (False, INVALID_REGION_MESSAGE)),
            (
                "access_denied",
                "us-east-1",
                None,
                [
                    _error(
                        "AccessDeniedException",
                        "User: arn:aws:iam::123456789012:user/example is not authorized to perform: "
                        "kinesis:ListStreams because no identity-based policy allows the kinesis:ListStreams action",
                    )
                ],
                (False, VALIDATION_ERROR_MESSAGES["AccessDeniedException"]),
            ),
            (
                "no_streams",
                "us-east-1",
                None,
                [ScriptedResponse(json={"StreamNames": [], "HasMoreStreams": False})],
                (False, NO_STREAMS_MESSAGE),
            ),
            (
                "unknown_stream",
                "us-east-1",
                "clicks",
                [_error("ResourceNotFoundException", "Stream clicks under account 123456789012 not found.")],
                (False, STREAM_NOT_FOUND_MESSAGE),
            ),
            (
                "valid",
                "us-east-1",
                None,
                [ScriptedResponse(json={"StreamNames": ["clicks"], "HasMoreStreams": False})],
                (True, None),
            ),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        region: str,
        stream_name: str | None,
        answers: list[ScriptedResponse],
        expected: tuple[bool, str | None],
    ) -> None:
        with scripted_network(answers):
            assert validate_credentials("AKIAEXAMPLE", "example-secret", None, region, stream_name) == expected
