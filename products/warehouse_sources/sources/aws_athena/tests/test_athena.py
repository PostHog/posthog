import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_athena.athena import (
    NO_RESULT_LOCATION_MESSAGE,
    VALIDATION_ERROR_MESSAGES,
    WORKGROUP_DISABLED_MESSAGE,
    WORKGROUP_NOT_FOUND_MESSAGE,
    athena_literal,
    validate_credentials,
    value_parser,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_athena.source import AwsAthenaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import UnexpectedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsathena import (
    AwsAthenaSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

ORDERS_TABLE = {
    "Table": {
        "Name": "orders",
        "DatabaseName": "analytics",
        "StorageDescriptor": {
            "Columns": [
                {"Name": "id", "Type": "bigint"},
                {"Name": "amount", "Type": "decimal(10,2)"},
                {"Name": "paid", "Type": "boolean"},
                {"Name": "updated_at", "Type": "timestamp"},
                {"Name": "tags", "Type": "array<string>"},
                {"Name": "note", "Type": "string"},
            ]
        },
        "PartitionKeys": [{"Name": "dt", "Type": "date"}],
    }
}
COLUMNS = ["id", "amount", "paid", "updated_at", "tags", "note", "dt"]


def config(**overrides: Any) -> AwsAthenaSourceConfig:
    values: dict[str, Any] = {
        "aws_access_key_id": "AKIAEXAMPLE",
        "aws_secret_access_key": "secret",
        "aws_session_token": None,
        "aws_region": "us-east-1",
        "database": "analytics",
        "workgroup": None,
        "output_location": None,
    }
    values.update(overrides)
    return AwsAthenaSourceConfig(**values)


def by_target(queues: Mapping[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Glue and Athena both post to `/`, so answers are routed by the operation in `X-Amz-Target`."""
    remaining = {target: list(answers) for target, answers in queues.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        target = request.headers.get("x-amz-target", "")
        queue = remaining.get(target.split(".")[-1])
        if not queue:
            raise UnexpectedRequest(f"no answer left for {target}")
        return queue.pop(0)

    return respond


def execution(state: str, athena_error: dict[str, Any] | None = None) -> ScriptedResponse:
    status: dict[str, Any] = {"State": state}
    if athena_error:
        status["AthenaError"] = athena_error
    return ScriptedResponse(json={"QueryExecution": {"QueryExecutionId": "q-1", "Status": status}})


def results(rows: list[list[str | None]], next_token: str | None = None, header: bool = False) -> ScriptedResponse:
    data = [[{"VarCharValue": value} if value is not None else {} for value in row] for row in rows]
    if header:
        data.insert(0, [{"VarCharValue": name} for name in COLUMNS])
    body: dict[str, Any] = {
        "ResultSet": {
            "Rows": [{"Data": row} for row in data],
            "ResultSetMetadata": {"ColumnInfo": [{"Name": name, "Type": "varchar"} for name in COLUMNS]},
        }
    }
    if next_token:
        body["NextToken"] = next_token
    return ScriptedResponse(json=body)


def aws_error(code: str, message: str) -> ScriptedResponse:
    return ScriptedResponse(status=400, json={"__type": code, "Message": message})


def table_rows(items: list[Any]) -> list[dict[str, Any]]:
    return [row for table in items for row in table.to_pylist()]


class TestSync:
    def test_runs_the_query_waits_for_it_and_reads_every_result_page_as_typed_rows(self) -> None:
        result = SourceDriver(AwsAthenaSource(), config()).run(
            "orders",
            by_target(
                {
                    "GetTable": [ScriptedResponse(json=ORDERS_TABLE)],
                    "StartQueryExecution": [ScriptedResponse(json={"QueryExecutionId": "q-1"})],
                    "GetQueryExecution": [execution("QUEUED"), execution("RUNNING"), execution("SUCCEEDED")],
                    "GetQueryResults": [
                        results(
                            [["1", "12.50", "true", "2024-03-02 10:00:00.123", "[a, b]", "it's", "2024-03-02"]],
                            next_token="p2",
                            header=True,
                        ),
                        results([["2", None, "false", "2024-03-02 11:00:00", "[]", "", "2024-03-02"]]),
                    ],
                }
            ),
        )

        assert result.raised is None
        targets = [request.headers["x-amz-target"] for request in result.requests]
        assert targets == [
            "AWSGlue.GetTable",
            "AmazonAthena.StartQueryExecution",
            "AmazonAthena.GetQueryExecution",
            "AmazonAthena.GetQueryExecution",
            "AmazonAthena.GetQueryExecution",
            "AmazonAthena.GetQueryResults",
            "AmazonAthena.GetQueryResults",
        ]
        start = result.requests[1].json()
        assert 'FROM "analytics"."orders"' in start["QueryString"]
        assert "WHERE" not in start["QueryString"]
        assert "ExecutionParameters" not in start
        assert start["QueryExecutionContext"] == {"Database": "analytics", "Catalog": "AwsDataCatalog"}
        assert start["WorkGroup"] == "primary"
        assert result.requests[6].json()["NextToken"] == "p2"
        # The header row on the first page is not data.
        assert table_rows(result.items) == [
            {
                "id": 1,
                "amount": Decimal("12.50"),
                "paid": True,
                "updated_at": dt.datetime(2024, 3, 2, 10, 0, 0, 123000),
                "tags": "[a, b]",
                "note": "it's",
                "dt": dt.date(2024, 3, 2),
            },
            {
                "id": 2,
                "amount": None,
                "paid": False,
                "updated_at": dt.datetime(2024, 3, 2, 11, 0),
                "tags": "[]",
                "note": "",
                "dt": dt.date(2024, 3, 2),
            },
        ]
        assert result.response is not None and result.response.primary_keys == ["id"]

    def test_an_incremental_read_passes_the_watermark_as_a_typed_execution_parameter(self) -> None:
        result = SourceDriver(
            AwsAthenaSource(), config(workgroup="analysts", output_location="s3://results/posthog/")
        ).run(
            "orders",
            by_target(
                {
                    "GetTable": [ScriptedResponse(json=ORDERS_TABLE)],
                    "StartQueryExecution": [ScriptedResponse(json={"QueryExecutionId": "q-1"})],
                    "GetQueryExecution": [execution("SUCCEEDED")],
                    "GetQueryResults": [results([], header=True)],
                }
            ),
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.Timestamp,
            db_incremental_field_last_value=dt.datetime(2024, 3, 1, 8, 30, tzinfo=dt.UTC),
        )

        assert result.raised is None
        start = result.requests[1].json()
        assert 'WHERE "updated_at" > ?' in start["QueryString"]
        assert start["QueryString"].endswith('ORDER BY "updated_at" ASC')
        # A `timestamp` column has no zone, so the UTC watermark is passed without one.
        assert start["ExecutionParameters"] == ["TIMESTAMP '2024-03-01 08:30:00.000000'"]
        assert start["WorkGroup"] == "analysts"
        assert start["ResultConfiguration"] == {"OutputLocation": "s3://results/posthog/"}

    def test_a_failed_query_fails_the_run_with_athenas_reason(self) -> None:
        result = SourceDriver(AwsAthenaSource(), config()).run(
            "orders",
            by_target(
                {
                    "GetTable": [ScriptedResponse(json=ORDERS_TABLE)],
                    "StartQueryExecution": [ScriptedResponse(json={"QueryExecutionId": "q-1"})],
                    "GetQueryExecution": [
                        execution(
                            "FAILED",
                            {
                                "ErrorCategory": 2,
                                "ErrorMessage": "COLUMN_NOT_FOUND: line 1:8: Column 'note' cannot be resolved",
                            },
                        )
                    ],
                }
            ),
        )

        assert str(result.raised) == (
            "AWS Athena query failed: USER_ERROR - COLUMN_NOT_FOUND: line 1:8: Column 'note' cannot be resolved"
        )
        assert "AmazonAthena.StopQueryExecution" not in [request.headers["x-amz-target"] for request in result.requests]

    def test_a_retried_start_sends_the_same_idempotency_token(self) -> None:
        result = SourceDriver(AwsAthenaSource(), config()).run(
            "orders",
            by_target(
                {
                    "GetTable": [ScriptedResponse(json=ORDERS_TABLE)],
                    "StartQueryExecution": [
                        ScriptedResponse(status=500, json={"__type": "InternalServerException", "Message": "Internal"}),
                        ScriptedResponse(json={"QueryExecutionId": "q-1"}),
                    ],
                    "GetQueryExecution": [execution("SUCCEEDED")],
                    "GetQueryResults": [results([], header=True)],
                }
            ),
        )

        assert result.raised is None
        tokens = [
            request.json().get("ClientRequestToken")
            for request in result.requests
            if request.headers["x-amz-target"] == "AmazonAthena.StartQueryExecution"
        ]
        assert len(tokens) == 2
        assert tokens[0] and tokens[0] == tokens[1]

    def test_a_query_still_running_at_the_deadline_is_stopped(self) -> None:
        result = SourceDriver(AwsAthenaSource(), config()).run(
            "orders",
            by_target(
                {
                    "GetTable": [ScriptedResponse(json=ORDERS_TABLE)],
                    "StartQueryExecution": [ScriptedResponse(json={"QueryExecutionId": "q-1"})],
                    "GetQueryExecution": [execution("RUNNING")] * 1000,
                    "StopQueryExecution": [ScriptedResponse(json={})],
                }
            ),
        )

        assert str(result.raised) == "AWS Athena query failed: TIMEOUT - query q-1 is still RUNNING"
        last = result.requests[-1]
        assert last.headers["x-amz-target"] == "AmazonAthena.StopQueryExecution"
        assert last.json() == {"QueryExecutionId": "q-1"}


class TestSchemas:
    def test_lists_every_glue_table_with_its_partition_keys_and_incremental_candidates(self) -> None:
        orders = ORDERS_TABLE["Table"]
        events = {"Name": "events", "StorageDescriptor": {"Columns": [{"Name": "payload", "Type": "struct<a:int>"}]}}

        with scripted_network(
            by_target(
                {
                    "GetTables": [
                        ScriptedResponse(json={"TableList": [orders], "NextToken": "t2"}),
                        ScriptedResponse(json={"TableList": [events]}),
                    ]
                }
            )
        ) as network:
            schemas = AwsAthenaSource().get_schemas(config(), team_id=1)

        assert [request.json().get("NextToken") for request in network.requests_log] == [None, "t2"]
        by_name = {schema.name: schema for schema in schemas}
        assert set(by_name) == {"orders", "events"}
        assert [column[0] for column in by_name["orders"].columns] == COLUMNS
        assert {field["field"] for field in by_name["orders"].incremental_fields} == {
            "id",
            "amount",
            "updated_at",
            "dt",
        }
        assert by_name["orders"].detected_primary_keys == ["id"]
        assert by_name["events"].supports_incremental is False

    def test_named_tables_are_fetched_one_by_one_and_a_dropped_one_is_left_out(self) -> None:
        with scripted_network(
            by_target(
                {
                    "GetTable": [
                        ScriptedResponse(json=ORDERS_TABLE),
                        aws_error("EntityNotFoundException", "Table gone not found"),
                    ]
                }
            )
        ) as network:
            schemas = AwsAthenaSource().get_schemas(config(), team_id=1, names=["orders", "gone"])

        assert [request.headers["x-amz-target"] for request in network.requests_log] == [
            "AWSGlue.GetTable",
            "AWSGlue.GetTable",
        ]
        assert [schema.name for schema in schemas] == ["orders"]


class TestAthenaLiteral:
    @pytest.mark.parametrize(
        ("value", "literal"),
        [
            ("it's", "'it''s'"),
            (
                dt.datetime(2024, 3, 1, 9, tzinfo=dt.timezone(dt.timedelta(hours=1))),
                "TIMESTAMP '2024-03-01 08:00:00.000000 UTC'",
            ),
            (dt.date(2024, 3, 1), "DATE '2024-03-01'"),
            (True, "TRUE"),
            (42, "42"),
            (Decimal("12.50"), "12.50"),
            # Athena takes no exponent in a numeric literal, and DECIMAL(38, 38) still fits.
            (Decimal("1E+2"), "100"),
            (Decimal("0." + "1" * 38), "0." + "1" * 38),
            (None, "NULL"),
        ],
    )
    def test_each_value_becomes_an_escaped_athena_literal(self, value: Any, literal: str) -> None:
        assert athena_literal(value) == literal

    def test_an_unsupported_value_is_refused_rather_than_stringified(self) -> None:
        with pytest.raises(TypeError):
            athena_literal(["a"])

    @pytest.mark.parametrize("text", ["1e1000000000", "1e-1000000000", "NaN", "Infinity"])
    def test_a_decimal_with_no_athena_literal_is_refused_before_it_is_written_out(self, text: str) -> None:
        # A row filter value arrives as text, so `1e1000000000` would otherwise render as a
        # gigabyte-long parameter before the query request leaves the worker.
        with pytest.raises(ValueError):
            athena_literal(Decimal(text))


class TestValueParser:
    @pytest.mark.parametrize(
        "arrow_type, text, expected",
        [
            # Glue declares an Iceberg timestamptz as `timestamp`, and Athena prints it with its zone.
            (pa.timestamp("us"), "2024-01-15 10:30:00.123456 UTC", dt.datetime(2024, 1, 15, 10, 30, 0, 123456)),
            (pa.timestamp("us"), "2024-01-15 10:30:00.123 +05:30", dt.datetime(2024, 1, 15, 5, 0, 0, 123000)),
            (
                pa.timestamp("us", tz="UTC"),
                "2024-01-15 10:30:00 America/New_York",
                dt.datetime(2024, 1, 15, 15, 30, tzinfo=dt.UTC),
            ),
            (pa.timestamp("us"), "2024-01-15 10:30:00", dt.datetime(2024, 1, 15, 10, 30)),
        ],
    )
    def test_a_zoned_timestamp_lands_in_utc(self, arrow_type: pa.DataType, text: str, expected: dt.datetime) -> None:
        parser = value_parser(arrow_type)
        assert parser is not None
        assert parser(text) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"aws_secret_access_key": ""}, "AWS access key ID and secret access key are required"),
            ({"aws_region": "frankfurt"}, "Enter an AWS region code, for example us-east-1."),
            ({"database": "  "}, "Enter the Glue database to sync tables from."),
            ({"output_location": "my-bucket/results"}, "Enter the S3 output location as s3://bucket/path/."),
        ],
    )
    def test_local_checks_fail_before_any_request(self, overrides: dict[str, Any], expected: str) -> None:
        with scripted_network([]) as network:
            assert validate_credentials(config(**overrides)) == (False, expected)

        assert network.requests == 0

    @pytest.mark.parametrize(
        ("overrides", "workgroup", "expected"),
        [
            (
                {},
                {"State": "ENABLED", "Configuration": {"ResultConfiguration": {"OutputLocation": "s3://r/"}}},
                (True, None),
            ),
            (
                {},
                {"State": "ENABLED", "Configuration": {"ManagedQueryResultsConfiguration": {"Enabled": True}}},
                (True, None),
            ),
            ({}, {"State": "ENABLED", "Configuration": {}}, (False, NO_RESULT_LOCATION_MESSAGE)),
            ({"output_location": "s3://r/"}, {"State": "ENABLED", "Configuration": {}}, (True, None)),
            ({}, {"State": "DISABLED", "Configuration": {}}, (False, WORKGROUP_DISABLED_MESSAGE)),
        ],
    )
    def test_the_workgroup_must_be_enabled_and_have_somewhere_to_write_results(
        self, overrides: dict[str, Any], workgroup: dict[str, Any], expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(
            by_target(
                {
                    "GetDatabase": [ScriptedResponse(json={"Database": {"Name": "analytics"}})],
                    "GetWorkGroup": [ScriptedResponse(json={"WorkGroup": {"Name": "primary", **workgroup}})],
                }
            )
        ):
            assert validate_credentials(config(**overrides)) == expected

    @pytest.mark.parametrize(
        ("answers", "expected"),
        [
            (
                {"GetDatabase": [aws_error("EntityNotFoundException", "Database analytics not found.")]},
                VALIDATION_ERROR_MESSAGES["EntityNotFoundException"],
            ),
            (
                {
                    "GetDatabase": [ScriptedResponse(json={"Database": {"Name": "analytics"}})],
                    "GetWorkGroup": [aws_error("InvalidRequestException", "WorkGroup primary is not found.")],
                },
                WORKGROUP_NOT_FOUND_MESSAGE,
            ),
            (
                {
                    "GetDatabase": [
                        aws_error(
                            "AccessDeniedException",
                            "User: arn:aws:iam::000000000000:user/example is not authorized to perform: glue:GetDatabase",
                        )
                    ]
                },
                VALIDATION_ERROR_MESSAGES["AccessDeniedException"],
            ),
        ],
    )
    def test_aws_errors_become_fixed_messages(self, answers: dict[str, list[ScriptedResponse]], expected: str) -> None:
        with scripted_network(by_target(answers)):
            assert validate_credentials(config()) == (False, expected)
