from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.dynamodb import (
    DynamoDBAPIError,
    DynamoDBClient,
    DynamoDBResumeConfig,
    DynamoDBRetryableError,
    deserialize_value,
    get_table_schemas,
    list_tables,
    validate_credentials,
    validate_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.settings import MAX_RETRY_ATTEMPTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.source import DynamoDBSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamodb import (
    DynamoDBSourceConfig,
)


def _client() -> DynamoDBClient:
    return DynamoDBClient(access_key_id="AKIATEST", secret_access_key="secret", region="us-east-1")


def _driver() -> SourceDriver:
    return SourceDriver(
        DynamoDBSource(),
        DynamoDBSourceConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
            aws_session_token=None,
        ),
    )


def _description(key_schema: list[dict[str, str]] | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"Table": {"KeySchema": key_schema or []}})


def _error(code: str, status: int = 400, message: str = "boom") -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"__type": f"com.amazonaws.dynamodb.v20120810#{code}", "message": message},
    )


class TestValidateRegion:
    @pytest.mark.parametrize(
        "region",
        [
            "",
            "US-EAST-1",
            "us-east-1.evil.com",
            "us-east-1/../",
            "evil.com",
            "us east 1",
            "us-east-1:443",
        ],
    )
    def test_rejects_anything_that_could_move_the_host(self, region: str) -> None:
        with pytest.raises(ValueError):
            validate_region(region)


class TestDeserializeValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ({"S": "hello"}, "hello"),
            ({"N": "42"}, 42),
            ({"N": "-7"}, -7),
            ({"N": "4.25"}, 4.25),
            ({"BOOL": True}, True),
            ({"BOOL": False}, False),
            ({"NULL": True}, None),
            ({"B": "aGVsbG8="}, "aGVsbG8="),
            ({"SS": ["a", "b"]}, ["a", "b"]),
            ({"NS": ["1", "2.5"]}, [1, 2.5]),
            ({"BS": ["aGk="]}, ["aGk="]),
            ({"L": [{"S": "a"}, {"N": "1"}]}, ["a", 1]),
            ({"M": {"k": {"S": "v"}}}, {"k": "v"}),
            ({"M": {"outer": {"L": [{"M": {"x": {"N": "1"}}}]}}}, {"outer": [{"x": 1}]}),
        ],
    )
    def test_converts_attribute_values(self, value: dict[str, Any], expected: Any) -> None:
        assert deserialize_value(value) == expected

    def test_number_wider_than_int64_degrades_to_float(self) -> None:
        result = deserialize_value({"N": "170141183460469231731687303715884105727"})
        assert isinstance(result, float)

    @pytest.mark.parametrize("value", [{}, {"S": "a", "N": "1"}, {"ZZ": "1"}])
    def test_rejects_malformed_values(self, value: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            deserialize_value(value)


class TestSigning:
    def test_signature_covers_the_body_so_two_payloads_differ(self) -> None:
        with scripted_network([ScriptedResponse(json={}), ScriptedResponse(json={})]) as network:
            client = _client()
            client.send("Scan", {"TableName": "users"})
            client.send("Scan", {"TableName": "orders"})

        assert network.requests_log[0].headers["authorization"] != network.requests_log[1].headers["authorization"]

    def test_invalid_region_is_rejected_before_any_request(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError):
                DynamoDBClient(access_key_id="AKIA", secret_access_key="s", region="evil.com")

        assert network.requests_log == []
        assert network.session_options == []


class TestErrorClassification:
    @pytest.mark.parametrize(
        "code, status, expected_retryable",
        [
            ("ThrottlingException", 400, True),
            ("ProvisionedThroughputExceededException", 400, True),
            ("RequestLimitExceeded", 400, True),
            ("InternalServerError", 500, True),
            ("ServiceUnavailable", 503, True),
            ("AccessDeniedException", 400, False),
            ("UnrecognizedClientException", 400, False),
            ("ValidationException", 400, False),
            ("ResourceNotFoundException", 400, False),
        ],
    )
    def test_error_codes_are_split_into_retryable_and_permanent(
        self, code: str, status: int, expected_retryable: bool
    ) -> None:
        with scripted_network([_error(code, status=status)]):
            client = _client()
            with pytest.raises(DynamoDBAPIError) as exc_info:
                client.send("Scan", {"TableName": "users"})

        assert exc_info.value.code == code
        assert exc_info.value.status_code == status
        assert isinstance(exc_info.value, DynamoDBRetryableError) is expected_retryable

    def test_unknown_5xx_is_retryable_even_without_a_known_code(self) -> None:
        with scripted_network([_error("SomethingNew", status=502)]):
            client = _client()
            with pytest.raises(DynamoDBRetryableError):
                client.send("Scan", {"TableName": "users"})

    def test_non_json_error_body_still_raises_a_typed_error(self) -> None:
        with scripted_network([ScriptedResponse(status=400, body=b"not json")]):
            client = _client()
            with pytest.raises(DynamoDBAPIError) as exc_info:
                client.send("Scan", {"TableName": "users"})

        assert exc_info.value.code == "UnknownError"

    def test_error_message_includes_the_code_so_non_retryable_matching_works(self) -> None:
        with scripted_network([_error("AccessDeniedException", message="no perms")]):
            client = _client()
            with pytest.raises(DynamoDBAPIError) as exc_info:
                client.send("Scan", {"TableName": "users"})

        assert "AccessDeniedException" in str(exc_info.value)
        assert "no perms" in str(exc_info.value)


class TestRequestRetries:
    def test_retries_are_bounded(self) -> None:
        with scripted_network([_error("ThrottlingException") for _ in range(MAX_RETRY_ATTEMPTS)]) as network:
            client = _client()
            with pytest.raises(DynamoDBRetryableError):
                client.request("ListTables", {})

        assert len(network.requests_log) == MAX_RETRY_ATTEMPTS

    def test_permanent_error_is_not_retried(self) -> None:
        with scripted_network([_error("AccessDeniedException")]) as network:
            client = _client()
            with pytest.raises(DynamoDBAPIError):
                client.request("ListTables", {})

        assert len(network.requests_log) == 1


class TestListTables:
    def test_pagination_follows_last_evaluated_table_name_and_terminates(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(json={"TableNames": ["a", "b"], "LastEvaluatedTableName": "b"}),
                ScriptedResponse(json={"TableNames": ["c"]}),
            ]
        ) as network:
            tables = list_tables(_client())

        assert tables == ["a", "b", "c"]
        assert "ExclusiveStartTableName" not in network.requests_log[0].json()
        assert network.requests_log[1].json()["ExclusiveStartTableName"] == "b"


class TestGetTableSchemas:
    def test_names_filter_skips_describing_unwanted_tables(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(json={"TableNames": ["users", "orders"]}),
                _description([{"AttributeName": "id", "KeyType": "HASH"}]),
            ]
        ) as network:
            schemas = get_table_schemas(_client(), names=["orders"])

        assert [schema.name for schema in schemas] == ["orders"]
        assert [request.headers["x-amz-target"] for request in network.requests_log] == [
            "DynamoDB_20120810.ListTables",
            "DynamoDB_20120810.DescribeTable",
        ]
        assert network.requests_log[1].json()["TableName"] == "orders"


class TestGetRows:
    def test_resumes_from_the_saved_cursor(self) -> None:
        saved_key = {"pk": {"S": "user#7"}}
        result = _driver().run(
            "users",
            [_description(), ScriptedResponse(json={"Items": [{"pk": {"S": "user#8"}}]})],
            resume_state=DynamoDBResumeConfig(table_name="users", exclusive_start_key=saved_key),
        )

        assert result.raised is None
        assert result.items == [[{"pk": "user#8"}]]
        assert result.requests[1].json()["ExclusiveStartKey"] == saved_key

    def test_cursor_saved_for_another_table_is_discarded(self) -> None:
        result = _driver().run(
            "users",
            [_description(), ScriptedResponse(json={"Items": []})],
            resume_state=DynamoDBResumeConfig(table_name="orders", exclusive_start_key={"order_id": {"S": "1"}}),
        )

        assert result.raised is None
        assert result.items == []
        assert "ExclusiveStartKey" not in result.requests[1].json()

    def test_empty_page_with_a_cursor_keeps_scanning(self) -> None:
        result = _driver().run(
            "users",
            [
                _description(),
                ScriptedResponse(json={"Items": [], "LastEvaluatedKey": {"pk": {"S": "a"}}}),
                ScriptedResponse(json={"Items": [{"pk": {"S": "b"}}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"pk": "b"}]]
        assert result.requests[2].json()["ExclusiveStartKey"] == {"pk": {"S": "a"}}


class TestValidateCredentials:
    def test_valid_credentials_probe_list_tables(self) -> None:
        with scripted_network([ScriptedResponse(json={"TableNames": []})]) as network:
            valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert (valid, message) == (True, None)
        assert network.requests_log[0].headers["x-amz-target"] == "DynamoDB_20120810.ListTables"

    @pytest.mark.parametrize(
        "code, expected_fragment",
        [
            ("UnrecognizedClientException", "access key"),
            ("AccessDeniedException", "dynamodb:ListTables"),
            ("ExpiredTokenException", "session token"),
        ],
    )
    def test_known_failures_map_to_an_actionable_message(self, code: str, expected_fragment: str) -> None:
        with scripted_network([_error(code)]):
            valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert valid is False
        assert message is not None and expected_fragment in message

    def test_bad_region_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials("AKIA", "secret", "not a region")

        assert valid is False
        assert message is not None and "valid AWS region" in message
        assert network.requests_log == []
        assert network.session_options == []

    def test_network_failure_reports_a_connectivity_message(self) -> None:
        with scripted_network([ConnectionError("nope")]) as network:
            valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert valid is False
        assert message is not None and "Could not reach DynamoDB" in message
        assert {request.path for request in network.requests_log} == {"/"}


class TestDynamoDBSourceResponse:
    def test_response_carries_the_table_key_and_streams_rows(self) -> None:
        result = _driver().run(
            "users",
            [
                _description(
                    [
                        {"AttributeName": "sk", "KeyType": "RANGE"},
                        {"AttributeName": "pk", "KeyType": "HASH"},
                    ]
                ),
                ScriptedResponse(json={"Items": [{"pk": {"S": "a"}, "sk": {"N": "1"}}]}),
            ],
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "users"
        assert result.response.primary_keys == ["pk", "sk"]
        # Scan walks partition-hash order, so no sort mode may be claimed.
        assert result.response.sort_mode is None
        assert result.items == [[{"pk": "a", "sk": 1}]]
