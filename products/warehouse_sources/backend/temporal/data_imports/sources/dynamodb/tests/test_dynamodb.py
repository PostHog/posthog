import json
import dataclasses
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest import mock

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.dynamodb import (
    DynamoDBAPIError,
    DynamoDBClient,
    DynamoDBResumeConfig,
    DynamoDBRetryableError,
    deserialize_item,
    deserialize_value,
    dynamodb_source,
    get_rows,
    get_table_schemas,
    list_tables,
    primary_keys_from_description,
    target_prefix,
    validate_credentials,
    validate_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.settings import MAX_RETRY_ATTEMPTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.dynamodb"


@dataclasses.dataclass
class FakeResponse:
    status_code: int = 200
    body: dict[str, Any] = dataclasses.field(default_factory=dict)
    json_decodable: bool = True

    def json(self) -> dict[str, Any]:
        if not self.json_decodable:
            raise ValueError("not json")
        return self.body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        self.calls.append({"url": url, "data": data, "headers": headers or {}, "timeout": timeout})
        if not self.responses:
            raise AssertionError("FakeSession ran out of queued responses")
        return self.responses.pop(0)

    def payload(self, index: int) -> dict[str, Any]:
        raw = self.calls[index]["data"]
        assert isinstance(raw, bytes)
        return cast(dict[str, Any], json.loads(raw.decode()))

    def target(self, index: int) -> str:
        return self.calls[index]["headers"]["X-Amz-Target"]


class FakeResumeManager(ResumableSourceManager[DynamoDBResumeConfig]):
    def __init__(self, state: DynamoDBResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[DynamoDBResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> DynamoDBResumeConfig | None:
        return self.state

    def save_state(self, data: DynamoDBResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _logger() -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, mock.MagicMock())


def _make_client(
    responses: list[FakeResponse],
    region: str = "us-east-1",
    session_token: str | None = None,
    api_version: str | None = None,
) -> tuple[DynamoDBClient, FakeSession]:
    session = FakeSession(responses)
    with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
        client = DynamoDBClient(
            access_key_id="AKIATEST",
            secret_access_key="secret",
            region=region,
            session_token=session_token,
            api_version=api_version,
        )
    return client, session


def _error(code: str, status: int = 400, message: str = "boom") -> FakeResponse:
    return FakeResponse(
        status_code=status,
        body={"__type": f"com.amazonaws.dynamodb.v20120810#{code}", "message": message},
    )


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[None]:
    with mock.patch("time.sleep"):
        yield


class TestValidateRegion:
    @pytest.mark.parametrize("region", ["us-east-1", "eu-west-2", "ap-southeast-3", "us-gov-west-1", "cn-north-1"])
    def test_accepts_region_codes(self, region: str) -> None:
        assert validate_region(region) == region

    def test_strips_surrounding_whitespace(self) -> None:
        assert validate_region("  us-east-1 ") == "us-east-1"

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


class TestTargetPrefix:
    @pytest.mark.parametrize(
        "api_version, expected",
        [("2012-08-10", "DynamoDB_20120810"), (None, "DynamoDB_20120810")],
    )
    def test_prefix_for_version(self, api_version: str | None, expected: str) -> None:
        assert target_prefix(api_version) == expected


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


class TestDeserializeItem:
    def test_flattens_every_attribute(self) -> None:
        item = {"pk": {"S": "user#1"}, "age": {"N": "30"}, "tags": {"SS": ["a"]}, "deleted": {"NULL": True}}
        assert deserialize_item(item) == {"pk": "user#1", "age": 30, "tags": ["a"], "deleted": None}


class TestSigning:
    def test_request_is_sigv4_signed_for_the_target_operation(self) -> None:
        client, session = _make_client([FakeResponse(body={"Items": []})])
        client.send("Scan", {"TableName": "users"})

        headers = session.calls[0]["headers"]
        assert session.calls[0]["url"] == "https://dynamodb.us-east-1.amazonaws.com/"
        assert headers["X-Amz-Target"] == "DynamoDB_20120810.Scan"
        assert headers["Content-Type"] == "application/x-amz-json-1.0"
        assert "X-Amz-Date" in headers
        assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
        assert "Credential=AKIATEST/" in headers["Authorization"]
        assert "/us-east-1/dynamodb/aws4_request" in headers["Authorization"]
        assert "Signature=" in headers["Authorization"]

    def test_signature_covers_the_body_so_two_payloads_differ(self) -> None:
        client, session = _make_client([FakeResponse(), FakeResponse()])
        client.send("Scan", {"TableName": "users"})
        client.send("Scan", {"TableName": "orders"})

        assert session.calls[0]["headers"]["Authorization"] != session.calls[1]["headers"]["Authorization"]

    def test_session_token_is_sent_when_supplied(self) -> None:
        client, session = _make_client([FakeResponse()], session_token="temp-token")
        client.send("ListTables", {})

        assert session.calls[0]["headers"]["X-Amz-Security-Token"] == "temp-token"

    def test_no_session_token_header_without_temporary_credentials(self) -> None:
        client, session = _make_client([FakeResponse()])
        client.send("ListTables", {})

        assert "X-Amz-Security-Token" not in session.calls[0]["headers"]

    def test_region_selects_the_endpoint(self) -> None:
        client, session = _make_client([FakeResponse()], region="eu-west-2")
        client.send("ListTables", {})

        assert session.calls[0]["url"] == "https://dynamodb.eu-west-2.amazonaws.com/"

    def test_invalid_region_is_rejected_before_any_request(self) -> None:
        with mock.patch(f"{_MODULE}.make_tracked_session") as make_session:
            with pytest.raises(ValueError):
                DynamoDBClient(access_key_id="AKIA", secret_access_key="s", region="evil.com")
        make_session.assert_not_called()

    def test_responses_are_excluded_from_http_sample_capture(self) -> None:
        # DynamoDB items carry arbitrary customer fields the name-based scrubber can't catch,
        # so the session must never stream response bodies into shared HTTP samples.
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=FakeSession([])) as make_session:
            DynamoDBClient(access_key_id="AKIA", secret_access_key="s", region="us-east-1")

        assert make_session.call_args.kwargs["capture"] is False


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
        client, _ = _make_client([_error(code, status=status)])

        with pytest.raises(DynamoDBAPIError) as exc_info:
            client.send("Scan", {"TableName": "users"})

        assert exc_info.value.code == code
        assert exc_info.value.status_code == status
        assert isinstance(exc_info.value, DynamoDBRetryableError) is expected_retryable

    def test_unknown_5xx_is_retryable_even_without_a_known_code(self) -> None:
        client, _ = _make_client([_error("SomethingNew", status=502)])

        with pytest.raises(DynamoDBRetryableError):
            client.send("Scan", {"TableName": "users"})

    def test_non_json_error_body_still_raises_a_typed_error(self) -> None:
        client, _ = _make_client([FakeResponse(status_code=400, json_decodable=False)])

        with pytest.raises(DynamoDBAPIError) as exc_info:
            client.send("Scan", {"TableName": "users"})

        assert exc_info.value.code == "UnknownError"

    def test_error_message_includes_the_code_so_non_retryable_matching_works(self) -> None:
        client, _ = _make_client([_error("AccessDeniedException", message="no perms")])

        with pytest.raises(DynamoDBAPIError) as exc_info:
            client.send("Scan", {"TableName": "users"})

        assert "AccessDeniedException" in str(exc_info.value)
        assert "no perms" in str(exc_info.value)


class TestRequestRetries:
    def test_retryable_error_is_retried_until_it_succeeds(self) -> None:
        client, session = _make_client(
            [_error("ThrottlingException"), _error("ThrottlingException"), FakeResponse(body={"TableNames": ["a"]})]
        )

        assert client.request("ListTables", {}) == {"TableNames": ["a"]}
        assert len(session.calls) == 3

    def test_retries_are_bounded(self) -> None:
        client, session = _make_client([_error("ThrottlingException") for _ in range(MAX_RETRY_ATTEMPTS)])

        with pytest.raises(DynamoDBRetryableError):
            client.request("ListTables", {})

        assert len(session.calls) == MAX_RETRY_ATTEMPTS

    def test_permanent_error_is_not_retried(self) -> None:
        client, session = _make_client([_error("AccessDeniedException")])

        with pytest.raises(DynamoDBAPIError):
            client.request("ListTables", {})

        assert len(session.calls) == 1

    def test_connection_errors_are_retried(self) -> None:
        client, session = _make_client([FakeResponse(body={"TableNames": []})])
        original_post = session.post
        calls: list[int] = []

        def flaky_post(*args: Any, **kwargs: Any) -> FakeResponse:
            calls.append(1)
            if len(calls) == 1:
                raise requests.ConnectionError("reset by peer")
            return original_post(*args, **kwargs)

        with mock.patch.object(session, "post", side_effect=flaky_post):
            assert client.request("ListTables", {}) == {"TableNames": []}

        assert len(calls) == 2


class TestListTables:
    def test_pagination_follows_last_evaluated_table_name_and_terminates(self) -> None:
        client, session = _make_client(
            [
                FakeResponse(body={"TableNames": ["a", "b"], "LastEvaluatedTableName": "b"}),
                FakeResponse(body={"TableNames": ["c"]}),
            ]
        )

        assert list_tables(client) == ["a", "b", "c"]
        assert "ExclusiveStartTableName" not in session.payload(0)
        assert session.payload(1)["ExclusiveStartTableName"] == "b"

    def test_empty_account_returns_no_tables(self) -> None:
        client, _ = _make_client([FakeResponse(body={})])

        assert list_tables(client) == []


class TestPrimaryKeys:
    @pytest.mark.parametrize(
        "key_schema, expected",
        [
            ([{"AttributeName": "pk", "KeyType": "HASH"}], ["pk"]),
            (
                [{"AttributeName": "sk", "KeyType": "RANGE"}, {"AttributeName": "pk", "KeyType": "HASH"}],
                ["pk", "sk"],
            ),
            ([], []),
        ],
    )
    def test_partition_key_comes_before_sort_key(self, key_schema: list[dict[str, str]], expected: list[str]) -> None:
        assert primary_keys_from_description({"KeySchema": key_schema}) == expected


class TestGetTableSchemas:
    def _responses(self) -> list[FakeResponse]:
        return [
            FakeResponse(body={"TableNames": ["users", "orders"]}),
            FakeResponse(
                body={
                    "Table": {
                        "KeySchema": [
                            {"AttributeName": "sk", "KeyType": "RANGE"},
                            {"AttributeName": "pk", "KeyType": "HASH"},
                        ],
                        "ItemCount": 12,
                    }
                }
            ),
            FakeResponse(body={"Table": {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}], "ItemCount": 3}}),
        ]

    def test_each_table_becomes_a_full_refresh_schema_with_detected_keys(self) -> None:
        client, _ = _make_client(self._responses())

        schemas = get_table_schemas(client)

        assert [schema.name for schema in schemas] == ["users", "orders"]
        assert schemas[0].detected_primary_keys == ["pk", "sk"]
        assert schemas[1].detected_primary_keys == ["id"]
        # Scan has no server-side timestamp filter, so nothing here may claim incremental sync.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert all(schema.row_count is None for schema in schemas)

    def test_row_counts_are_only_fetched_when_asked_for(self) -> None:
        client, _ = _make_client(self._responses())

        schemas = get_table_schemas(client, with_counts=True)

        assert [schema.row_count for schema in schemas] == [12, 3]

    def test_names_filter_skips_describing_unwanted_tables(self) -> None:
        client, session = _make_client(
            [
                FakeResponse(body={"TableNames": ["users", "orders"]}),
                FakeResponse(body={"Table": {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}}),
            ]
        )

        schemas = get_table_schemas(client, names=["orders"])

        assert [schema.name for schema in schemas] == ["orders"]
        assert [session.target(index) for index in range(len(session.calls))] == [
            "DynamoDB_20120810.ListTables",
            "DynamoDB_20120810.DescribeTable",
        ]
        assert session.payload(1)["TableName"] == "orders"


class TestGetRows:
    def test_scan_pages_are_yielded_deserialized_and_checkpointed(self) -> None:
        last_key = {"pk": {"S": "user#1"}}
        client, session = _make_client(
            [
                FakeResponse(
                    body={"Items": [{"pk": {"S": "user#1"}, "age": {"N": "30"}}], "LastEvaluatedKey": last_key}
                ),
                FakeResponse(body={"Items": [{"pk": {"S": "user#2"}, "age": {"N": "31"}}]}),
            ]
        )
        manager = FakeResumeManager()

        batches = list(get_rows(client, "users", _logger(), manager))

        assert batches == [[{"pk": "user#1", "age": 30}], [{"pk": "user#2", "age": 31}]]
        assert "ExclusiveStartKey" not in session.payload(0)
        assert session.payload(1)["ExclusiveStartKey"] == last_key
        # State is saved once, after the page that produced the cursor was already yielded.
        assert manager.saved == [DynamoDBResumeConfig(table_name="users", exclusive_start_key=last_key)]
        assert manager.cleared is True

    def test_resumes_from_the_saved_cursor(self) -> None:
        saved_key = {"pk": {"S": "user#7"}}
        client, session = _make_client([FakeResponse(body={"Items": [{"pk": {"S": "user#8"}}]})])
        manager = FakeResumeManager(DynamoDBResumeConfig(table_name="users", exclusive_start_key=saved_key))

        batches = list(get_rows(client, "users", _logger(), manager))

        assert batches == [[{"pk": "user#8"}]]
        assert session.payload(0)["ExclusiveStartKey"] == saved_key

    def test_cursor_saved_for_another_table_is_discarded(self) -> None:
        client, session = _make_client([FakeResponse(body={"Items": []})])
        manager = FakeResumeManager(
            DynamoDBResumeConfig(table_name="orders", exclusive_start_key={"order_id": {"S": "1"}})
        )

        assert list(get_rows(client, "users", _logger(), manager)) == []
        assert "ExclusiveStartKey" not in session.payload(0)

    def test_empty_page_with_a_cursor_keeps_scanning(self) -> None:
        client, _ = _make_client(
            [
                FakeResponse(body={"Items": [], "LastEvaluatedKey": {"pk": {"S": "a"}}}),
                FakeResponse(body={"Items": [{"pk": {"S": "b"}}]}),
            ]
        )

        assert list(get_rows(client, "users", _logger(), FakeResumeManager())) == [[{"pk": "b"}]]


class TestValidateCredentials:
    def test_valid_credentials_probe_list_tables(self) -> None:
        session = FakeSession([FakeResponse(body={"TableNames": []})])
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("AKIA", "secret", "us-east-1") == (True, None)

        assert session.target(0) == "DynamoDB_20120810.ListTables"

    @pytest.mark.parametrize(
        "code, expected_fragment",
        [
            ("UnrecognizedClientException", "access key"),
            ("AccessDeniedException", "dynamodb:ListTables"),
            ("ExpiredTokenException", "session token"),
        ],
    )
    def test_known_failures_map_to_an_actionable_message(self, code: str, expected_fragment: str) -> None:
        session = FakeSession([_error(code)])
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert valid is False
        assert message is not None and expected_fragment in message

    def test_unknown_error_code_is_reported_verbatim(self) -> None:
        session = FakeSession([_error("SomeNewException")])
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert valid is False
        assert message is not None and "SomeNewException" in message

    def test_bad_region_fails_without_a_request(self) -> None:
        with mock.patch(f"{_MODULE}.make_tracked_session") as make_session:
            valid, message = validate_credentials("AKIA", "secret", "not a region")

        assert valid is False
        assert message is not None and "valid AWS region" in message
        make_session.assert_not_called()

    def test_network_failure_reports_a_connectivity_message(self) -> None:
        session = FakeSession([])
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            with mock.patch.object(session, "post", side_effect=requests.ConnectionError("nope")):
                valid, message = validate_credentials("AKIA", "secret", "us-east-1")

        assert valid is False
        assert message is not None and "Could not reach DynamoDB" in message


class TestDynamoDBSourceResponse:
    def test_response_carries_the_table_key_and_streams_rows(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    body={
                        "Table": {
                            "KeySchema": [
                                {"AttributeName": "sk", "KeyType": "RANGE"},
                                {"AttributeName": "pk", "KeyType": "HASH"},
                            ]
                        }
                    }
                ),
                FakeResponse(body={"Items": [{"pk": {"S": "a"}, "sk": {"N": "1"}}]}),
            ]
        )
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            response = dynamodb_source(
                access_key_id="AKIA",
                secret_access_key="secret",
                region="us-east-1",
                table_name="users",
                logger=_logger(),
                resumable_source_manager=FakeResumeManager(),
            )

        assert response.name == "users"
        assert response.primary_keys == ["pk", "sk"]
        # Scan walks partition-hash order, so no sort mode may be claimed.
        assert response.sort_mode is None
        assert list(cast("Iterable[Any]", response.items())) == [[{"pk": "a", "sk": 1}]]

    def test_table_without_a_key_schema_yields_no_primary_keys(self) -> None:
        session = FakeSession([FakeResponse(body={"Table": {}}), FakeResponse(body={"Items": []})])
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            response = dynamodb_source(
                access_key_id="AKIA",
                secret_access_key="secret",
                region="us-east-1",
                table_name="users",
                logger=_logger(),
                resumable_source_manager=FakeResumeManager(),
            )

        assert response.primary_keys is None
