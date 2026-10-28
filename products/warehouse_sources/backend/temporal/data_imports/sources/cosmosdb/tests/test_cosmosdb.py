from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cosmosdb.cosmosdb import (
    CosmosDBResumeConfig,
    CosmosDBRetryableError,
    CosmosDBTsCursor,
    decode_account_key,
    master_key_signature,
    normalize_account_endpoint,
    partition_key_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cosmosdb.source import CosmosDBSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cosmosdb import (
    CosmosDBSourceConfig,
)

# A syntactically valid 64-byte key, as the Azure portal issues them (the value itself is made up).
ACCOUNT_KEY = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU2Nzg5"
ENDPOINT = "https://unit-test.documents.azure.com"
# Each run reads documents written before now minus five minutes.
NOW = datetime(2023, 11, 14, 22, 18, 20, tzinfo=UTC)
CURSOR_FLOOR = 1700000000
COLLECTION = {"id": "orders", "partitionKey": {"paths": ["/tenantId"], "kind": "Hash"}}


def _driver() -> SourceDriver:
    return SourceDriver(
        CosmosDBSource(), CosmosDBSourceConfig(account_endpoint=ENDPOINT, key=ACCOUNT_KEY, database="shop")
    )


def _collection() -> ScriptedResponse:
    return ScriptedResponse(json=COLLECTION)


def _page(documents: list[dict[str, Any]], continuation: str | None = None) -> ScriptedResponse:
    headers = {"x-ms-continuation": continuation} if continuation else {}
    return ScriptedResponse(json={"_rid": "rid", "Documents": documents, "_count": len(documents)}, headers=headers)


class TestMasterKeySignature:
    def test_matches_the_worked_example_from_the_rest_auth_docs(self) -> None:
        key = decode_account_key(
            "dsZQi3KtZmCv1ljt3VNWNm7sQUF1y5rJfC6kv5JiwvW0EndXdDku/dkKBp8/ufDToSxLzR4y+O/0H/t4bQtVNw=="
        )
        signature = master_key_signature(key, "GET", "dbs", "dbs/ToDoList", "Thu, 27 Apr 2017 00:51:12 GMT")

        assert unquote(signature) == "type=master&ver=1.0&sig=c09PEVJrgp2uQRkr934kFbTqhByc7TVr3OHyqlu+c+c="


class TestNormalizeAccountEndpoint:
    @pytest.mark.parametrize(
        ("endpoint", "expected"),
        [
            ("https://acme.documents.azure.com", "https://acme.documents.azure.com"),
            ("https://acme.documents.azure.com:443/", "https://acme.documents.azure.com:443"),
            ("  acme.documents.azure.com  ", "https://acme.documents.azure.com"),
        ],
    )
    def test_trims_to_scheme_and_host(self, endpoint: str, expected: str) -> None:
        assert normalize_account_endpoint(endpoint) == expected

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://acme.documents.azure.com",
            "https://acme.documents.azure.com/dbs/other",
            "https://acme.documents.azure.com?x=1",
            "https://user:pw@acme.documents.azure.com",
            "",
        ],
    )
    def test_rejects_anything_that_could_repoint_the_signed_request(self, endpoint: str) -> None:
        with pytest.raises(ValueError):
            normalize_account_endpoint(endpoint)


class TestPartitionKeyValue:
    @pytest.mark.parametrize(
        ("document", "paths", "expected"),
        [
            ({"tenantId": "t-1"}, ("/tenantId",), '"t-1"'),
            ({"tenantId": "1"}, ("/tenantId",), '"1"'),
            ({"tenantId": 1}, ("/tenantId",), "1"),
            ({"tenantId": True}, ("/tenantId",), "true"),
            ({"tenantId": None}, ("/tenantId",), "null"),
            ({"tenantId": ""}, ("/tenantId",), '""'),
            ({"id": "x"}, ("/tenantId",), ""),
            ({"address": {"city": "Oslo"}}, ("/address/city",), '"Oslo"'),
            ({"address": "flat"}, ("/address/city",), ""),
            ({"tenant/key": "t-1"}, ('/"tenant/key"',), '"t-1"'),
            ({"a": {'say "hi"': 2}}, ('/a/"say \\"hi\\""',), "2"),
            ({"tenantId": "t-1", "region": "eu"}, ("/tenantId", "/region"), '["\\"t-1\\"","\\"eu\\""]'),
            ({"tenantId": "t-1"}, ("/tenantId", "/region"), '["\\"t-1\\"",""]'),
            ({"tenantId": "t-1", "region": None}, ("/tenantId", "/region"), '["\\"t-1\\"","null"]'),
            ({"id": "x"}, (), ""),
        ],
    )
    def test_resolves_the_path_to_one_string(self, document: dict[str, Any], paths: tuple[str, ...], expected: str):
        assert partition_key_value(document, paths) == expected

    def test_keys_that_differ_in_type_or_presence_stay_distinct(self) -> None:
        documents: list[dict[str, Any]] = [{"k": "1"}, {"k": 1}, {"k": ""}, {"k": None}, {}, {"k": True}, {"k": "true"}]

        assert len({partition_key_value(document, ("/k",)) for document in documents}) == len(documents)


class _SourceWithCursor(CosmosDBSource):
    """Hands the source a cursor manager, as the pipeline does for a cursor source."""

    def __init__(self, stored: CosmosDBTsCursor | None = None) -> None:
        super().__init__()
        self.cursor_manager = SourceCursorManager(CosmosDBTsCursor, stored, self)

    def source_for_pipeline(
        self,
        config: CosmosDBSourceConfig,
        resumable_source_manager: ResumableSourceManager[CosmosDBResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        inputs.source_cursor = self.cursor_manager
        return super().source_for_pipeline(config, resumable_source_manager, inputs)


def _config() -> CosmosDBSourceConfig:
    return CosmosDBSourceConfig(account_endpoint=ENDPOINT, key=ACCOUNT_KEY, database="shop")


class TestQueryDocuments:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_walks_continuation_tokens_and_stages_each_before_its_page(self) -> None:
        result = _driver().run(
            "orders",
            [
                _collection(),
                _page([{"id": "1", "tenantId": "a", "_ts": 10}], continuation="tok-2"),
                _page([{"id": "2", "tenantId": "b", "_ts": 11}], continuation="tok-3"),
                _page([{"id": "3", "tenantId": "a", "_ts": 12}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/dbs/shop/colls/orders"] + ["/dbs/shop/colls/orders/docs"] * 3
        assert [request.headers.get("x-ms-continuation") for request in result.requests[1:]] == [None, "tok-2", "tok-3"]
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert [row["_partition_key"] for row in result.rows] == ['"a"', '"b"', '"a"']
        assert result.saved_states == [
            CosmosDBResumeConfig(continuation="tok-2"),
            CosmosDBResumeConfig(continuation="tok-3"),
        ]
        assert result.committed_states == result.saved_states
        assert result.completed_state is None

    @pytest.mark.parametrize(
        ("stored", "inputs", "expected_floor", "expected_staged"),
        [
            (None, {}, None, None),
            (
                CosmosDBTsCursor(ts_floor=1699995000),
                {
                    "incremental_field": "_ts",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": 1,
                },
                None,
                None,
            ),
            (None, {"incremental_field": "_ts"}, None, CosmosDBTsCursor(ts_floor=CURSOR_FLOOR)),
            (
                None,
                {"incremental_field": "_ts", "db_incremental_field_last_value": 1699990000},
                1699990000,
                CosmosDBTsCursor(ts_floor=CURSOR_FLOOR),
            ),
            (
                CosmosDBTsCursor(ts_floor=1699995000),
                {"incremental_field": "_ts", "db_incremental_field_last_value": 1699999999},
                1699995000,
                CosmosDBTsCursor(ts_floor=CURSOR_FLOOR),
            ),
        ],
    )
    def test_incremental_runs_read_from_the_cursor_with_no_upper_bound(
        self,
        stored: CosmosDBTsCursor | None,
        inputs: dict[str, Any],
        expected_floor: int | None,
        expected_staged: CosmosDBTsCursor | None,
    ) -> None:
        source = _SourceWithCursor(stored)
        result = SourceDriver(source, _config()).run(
            "orders", [_collection(), _page([{"id": "1", "tenantId": "a", "_ts": 1}])], **inputs
        )

        assert result.raised is None
        query_request = result.requests[1]
        if expected_floor is None:
            assert query_request.json() == {"query": "SELECT * FROM c", "parameters": []}
        else:
            assert query_request.json() == {
                "query": "SELECT * FROM c WHERE c._ts >= @floor",
                "parameters": [{"name": "@floor", "value": expected_floor}],
            }
        assert query_request.headers["x-ms-documentdb-query-enablecrosspartition"] == "True"
        assert query_request.headers["x-ms-version"] == "2018-12-31"
        assert source.cursor_manager.staged == expected_staged

    def test_resume_replays_the_saved_token_and_hands_on_the_first_attempts_floor(self) -> None:
        source = _SourceWithCursor(CosmosDBTsCursor(ts_floor=30))
        result = SourceDriver(source, _config()).run(
            "orders",
            [_collection(), _page([{"id": "9", "tenantId": "a", "_ts": 50}])],
            resume_state=CosmosDBResumeConfig(continuation="tok-7", ts_floor=40, next_ts_floor=90),
            incremental_field="_ts",
        )

        assert result.raised is None
        query_request = result.requests[1]
        assert query_request.headers["x-ms-continuation"] == "tok-7"
        assert query_request.json()["parameters"] == [{"name": "@floor", "value": 40}]
        assert source.cursor_manager.staged == CosmosDBTsCursor(ts_floor=90)

    def test_empty_pages_with_a_token_keep_walking(self) -> None:
        result = _driver().run(
            "orders",
            [
                _collection(),
                _page([], continuation="tok-2"),
                _page([], continuation="tok-3"),
                _page([{"id": "1", "tenantId": "a", "_ts": 1}]),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 4
        assert [row["id"] for row in result.rows] == ["1"]

    def test_throttle_honours_retry_after_ms_then_succeeds(self) -> None:
        throttled = ScriptedResponse(
            status=429,
            json={"code": "TooManyRequests", "message": "Request rate is large."},
            headers={"x-ms-retry-after-ms": "250"},
        )
        answers = iter([_collection(), *[throttled] * 7, _page([{"id": "1", "tenantId": "a", "_ts": 1}])])

        def respond(_request: RecordedRequest) -> ScriptedResponse:
            return next(answers)

        result = _driver().run("orders", respond)

        assert result.raised is None
        assert len(result.requests) == 9
        assert [row["id"] for row in result.rows] == ["1"]

    def test_a_dropped_connection_is_retried_within_the_budget(self) -> None:
        result = _driver().run(
            "orders",
            [_collection(), ConnectionResetError(), _page([{"id": "1", "tenantId": "a", "_ts": 1}])],
        )

        assert result.raised is None
        assert len(result.requests) == 3
        assert [row["id"] for row in result.rows] == ["1"]

    def test_a_throttle_wait_longer_than_the_budget_fails_without_retrying(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/dbs/shop/colls/orders":
                return _collection()
            return ScriptedResponse(status=429, json={"code": "TooManyRequests"}, headers={"Retry-After": "86400"})

        result = _driver().run("orders", respond)

        assert isinstance(result.raised, CosmosDBRetryableError)
        assert len(result.requests) == 2

    def test_retries_stop_before_a_full_attempt_would_overrun_five_minutes(self) -> None:
        unavailable = ScriptedResponse(status=503, json={"code": "ServiceUnavailable"}, headers={"Retry-After": "60"})

        def respond(request: RecordedRequest) -> ScriptedResponse:
            return _collection() if request.path == "/dbs/shop/colls/orders" else unavailable

        result = _driver().run("orders", respond)

        assert isinstance(result.raised, CosmosDBRetryableError)
        # Waits of 60 s at 0 s and 60 s still leave room for a full 150 s attempt; a third does not.
        assert len(result.requests) == 1 + 3

    def test_bad_key_surfaces_the_vendor_error(self) -> None:
        result = _driver().run(
            "orders",
            [
                ScriptedResponse(
                    status=401,
                    json={
                        "code": "Unauthorized",
                        "message": "The input authorization token can't serve the request. The wrong key is being used or the expected payload is not built as per the protocol.",
                    },
                )
            ],
        )

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url:" in str(result.raised)
        assert "The wrong key is being used" in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "expected_ok", "expected_fragment"),
        [
            (ScriptedResponse(json={"DocumentCollections": [COLLECTION], "_count": 1}), True, None),
            (
                ScriptedResponse(
                    status=404,
                    json={"code": "NotFound", "message": "Entity with the specified id does not exist in the system."},
                ),
                False,
                "No database named shop",
            ),
        ],
    )
    def test_maps_the_collection_probe_to_a_message(
        self, response: ScriptedResponse, expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with scripted_network([response]) as network:
            ok, message = validate_credentials(ENDPOINT, ACCOUNT_KEY, "shop", "2018-12-31")

        assert ok is expected_ok
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message
        assert network.requests_log[0].path == "/dbs/shop/colls"
        assert network.requests_log[0].headers["authorization"].startswith("type%3Dmaster%26ver%3D1.0%26sig%3D")

    def test_rejects_a_key_that_is_not_base64_without_a_request(self) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials(ENDPOINT, "not a key", "shop", "2018-12-31")

        assert ok is False
        assert message is not None and "not valid" in message
        assert network.requests_log == []
