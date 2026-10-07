import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import patch

from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.neo4j import Neo4jSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.neo4j import (
    Neo4jClient,
    Neo4jQueryError,
    neo4j_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.source import Neo4jSource


@pytest.fixture
def config() -> Neo4jSourceConfig:
    return Neo4jSourceConfig(
        host="https://graph.example.com:7473/", database="neo4j", username="reader", password="test-password"
    )


@pytest.fixture(autouse=True)
def safe_host() -> Iterator[None]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid",
        return_value=(True, None),
    ):
        yield


@pytest.fixture
def transport() -> Iterator[tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]]]:
    requests: list[PreparedRequest] = []
    replies: list[tuple[int, dict[str, Any]]] = []

    def send(_adapter: object, request: PreparedRequest, **_kwargs: object) -> Response:
        requests.append(request)
        status, payload = replies.pop(0)
        response = Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response._content = json.dumps(payload).encode()
        return response

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport.TrackedHTTPAdapter.send",
        new=send,
    ):
        yield requests, replies


@pytest.mark.parametrize("prefix", ["node", "rel"])
@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_full_refresh_pagination_and_rows(config: Neo4jSourceConfig, transport: Any, prefix: str, count: int) -> None:
    requests, replies = transport
    fields = (
        ["element_id", "properties", "labels"]
        if prefix == "node"
        else ["element_id", "properties", "start_element_id", "end_element_id"]
    )
    values = [
        [f"id-{index}", {"amount": index, "tags": ["example"], "created": "2026-01-01"}]
        + ([["Order", "Record"]] if prefix == "node" else ["start-1", "end-1"])
        for index in range(count)
    ]
    for offset in range(0, count + 1, 2):
        replies.append((202, {"data": {"fields": fields, "values": values[offset : offset + 2]}}))
    with patch("products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.neo4j.PAGE_SIZE", 2):
        result = neo4j_source(config, 1, f"{prefix}_Order")
        rows = [row for page in result.items() for row in page]
    assert len(rows) == count
    assert [row["element_id"] for row in rows] == [f"id-{index}" for index in range(count)]
    for index, row in enumerate(rows):
        assert row["amount"] == index
        assert row["tags"] == ["example"]
        assert "properties" not in row
        if prefix == "node":
            assert row["labels"] == ["Order", "Record"]
        else:
            assert row["start_element_id"] == "start-1"
            assert row["end_element_id"] == "end-1"
    assert len(requests) == count // 2 + 1
    for index, request in enumerate(requests):
        assert request.method == "POST"
        assert request.url == "https://graph.example.com:7473/db/neo4j/query/v2"
        assert request.headers["Authorization"] == "Basic cmVhZGVyOnRlc3QtcGFzc3dvcmQ="
        assert request.headers["Accept"] == "application/json"
        body = json.loads(request.body)
        assert body["parameters"] == {"offset": index * 2, "limit": 2}
        assert body["accessMode"] == "Read"
        assert "ORDER BY elementId(x) SKIP $offset LIMIT $limit" in body["statement"]


@pytest.mark.parametrize("prefix", ["node", "rel"])
@pytest.mark.parametrize("label", ["two words", "a`b", "x`) MATCH (secret) RETURN secret //", "日本語", r"x\u0060"])
def test_identifiers_are_quoted(config: Neo4jSourceConfig, transport: Any, prefix: str, label: str) -> None:
    requests, replies = transport
    replies.append((202, {"data": {"fields": [], "values": []}}))
    list(Neo4jClient(config, 1).rows(f"{prefix}_{label}"))
    body = json.loads(requests[0].body)
    statement = body["statement"]
    if "\\" in label:
        assert label not in statement
        assert body["parameters"]["name"] == label
        assert ("WHERE $name IN labels(x)" if prefix == "node" else "WHERE type(x) = $name") in statement
    else:
        escaped = label.replace("`", "``")
        assert f":`{escaped}`" in statement


@pytest.mark.parametrize("table", ["", "nodes", "node_", "rel_", "other_Person"])
def test_invalid_table_does_not_send_request(config: Neo4jSourceConfig, transport: Any, table: str) -> None:
    with pytest.raises(ValueError, match="Invalid Neo4j table"):
        neo4j_source(config, 1, table)
    assert not transport[0]


@pytest.mark.parametrize("count", [2, 3])
def test_row_cap_does_not_silently_truncate(config: Neo4jSourceConfig, transport: Any, count: int) -> None:
    requests, replies = transport
    replies.append(
        (
            202,
            {
                "data": {
                    "fields": ["element_id", "properties", "labels"],
                    "values": [["id-0", {}, ["Person"]], ["id-1", {}, ["Person"]]],
                }
            },
        )
    )
    replies.append(
        (
            202,
            {
                "data": {
                    "fields": ["element_id", "properties", "labels"],
                    "values": [["id-2", {}, ["Person"]]] if count == 3 else [],
                }
            },
        )
    )
    with (
        patch("products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.neo4j.PAGE_SIZE", 2),
        patch("products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.neo4j.MAX_ROWS_PER_SYNC", 2),
    ):
        iterator = Neo4jClient(config, 1).rows("node_Person")
        assert len(next(iterator)) == 2
        if count == 3:
            with pytest.raises(ValueError, match="Neo4j sync row limit exceeded"):
                next(iterator)
        else:
            assert list(iterator) == []
    assert json.loads(requests[-1].body)["parameters"] == {"offset": 2, "limit": 1}


@pytest.mark.parametrize("key", ["element_id", "labels"])
def test_reserved_properties_fail_before_data_is_lost(config: Neo4jSourceConfig, transport: Any, key: str) -> None:
    transport[1].append(
        (
            202,
            {
                "data": {
                    "fields": ["element_id", "properties", "labels"],
                    "values": [["id-1", {key: "property-value"}, ["Person"]]],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="Neo4j property conflicts"):
        list(Neo4jClient(config, 1).rows("node_Person"))


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (401, None, "authentication failed"),
        (403, None, "denied access"),
        (404, None, "Query API was not found"),
        (202, "Neo.ClientError.Security.Unauthorized", "authentication failed"),
        (202, "Neo.ClientError.Security.CredentialsExpired", "password has expired"),
        (202, "Neo.ClientError.Security.Forbidden", "denied access"),
        (202, "Neo.ClientError.Database.DatabaseNotFound", "could not find the database"),
        (202, "Neo.ClientError.Statement.SyntaxError", "rejected the query"),
        (503, None, "Could not connect"),
        (202, "Neo.TransientError.General.DatabaseUnavailable", "Could not connect"),
        (307, None, "final HTTPS address"),
    ],
)
def test_credential_error_mapping(
    config: Neo4jSourceConfig, transport: Any, status: int, code: str | None, message: str
) -> None:
    transport[1].append((status, {"errors": [{"code": code, "message": "private details"}]} if code else {}))
    valid, error = validate_credentials(config, 1)
    assert not valid
    assert error is not None and message in error
    assert "private details" not in error
    assert len(transport[0]) == 1
    if status == 503 or (code and code.startswith("Neo.TransientError")):
        assert not any(pattern in (code or "503 Client Error") for pattern in Neo4jSource().get_non_retryable_errors())


def test_query_error_with_partial_data_is_not_imported(config: Neo4jSourceConfig, transport: Any) -> None:
    transport[1].append(
        (
            202,
            {
                "data": {"fields": ["element_id", "properties"], "values": [["id-1", {}]]},
                "errors": [{"code": "Neo.TransientError.General.DatabaseUnavailable"}],
            },
        )
    )
    with pytest.raises(Neo4jQueryError):
        list(Neo4jClient(config, 1).rows("node_Person"))


def test_credential_probe_is_one_cheap_query(config: Neo4jSourceConfig, transport: Any) -> None:
    transport[1].append((202, {"data": {"fields": ["ok"], "values": [[1]]}}))
    assert validate_credentials(config, 1) == (True, None)
    assert len(transport[0]) == 1
    assert json.loads(transport[0][0].body)["statement"] == "RETURN 1 AS ok"


@pytest.mark.parametrize(
    "host",
    [
        "http://graph.example.com",
        "https://reader:password@graph.example.com",
        "https://graph.example.com/path",
        "https://graph.example.com?query=1",
        "https://graph.example.com#fragment",
        "https://graph.example.com:wrong",
        "https://graph.example.com:99999",
        "https://graph.example.com\\@other.example.com",
        "https://graph.example.com\n",
        "neo4j+s://graph.example.com",
        "https://",
        "https://[broken",
    ],
)
def test_invalid_hosts_never_receive_credentials(config: Neo4jSourceConfig, transport: Any, host: str) -> None:
    config.host = host
    assert validate_credentials(config, 1)[0] is False
    assert not transport[0]


def test_internal_host_is_rejected(config: Neo4jSourceConfig, transport: Any) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid",
        return_value=(False, "Internal IP"),
    ) as check:
        assert validate_credentials(config, 1)[0] is False
    check.assert_called_once_with("graph.example.com", 1)
    assert not transport[0]


@pytest.mark.parametrize("database", ["", "../system", "a/b", "a?query", "a#fragment"])
def test_invalid_database_is_rejected(config: Neo4jSourceConfig, transport: Any, database: str) -> None:
    config.database = database
    assert validate_credentials(config, 1) == (False, "Enter a valid Neo4j database name.")
    assert not transport[0]
