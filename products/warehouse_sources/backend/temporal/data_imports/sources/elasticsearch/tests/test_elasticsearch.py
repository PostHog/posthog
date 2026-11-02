from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.elasticsearch import (
    CLUSTER_UNAVAILABLE_ERROR,
    PAGE_SIZE,
    TLS_ERROR,
    UNEXPECTED_RESPONSE_ERROR,
    UNREACHABLE_ERROR,
    ElasticsearchAuth,
    coerce_float_fields,
    elasticsearch_source,
    get_float_field_paths,
    list_data_streams,
    list_indices,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.source import ElasticsearchSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.elasticsearch import (
    ElasticsearchAuthMethodConfig,
    ElasticsearchSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.elasticsearch"


def _driver() -> SourceDriver:
    return SourceDriver(
        ElasticsearchSource(),
        ElasticsearchSourceConfig(
            host="https://es.example.com",
            auth_method=ElasticsearchAuthMethodConfig(selection="api_key", api_key="k"),
        ),
    )


_NOT_A_DATA_STREAM = ScriptedResponse(status=404, json={"error": {"type": "index_not_found_exception"}, "status": 404})


def _data_stream_body(*names: str, **flags: bool) -> dict[str, Any]:
    return {"data_streams": [{"name": name, "hidden": False, "system": False, **flags} for name in names]}


def _scroll_page(hits: list[dict[str, Any]], scroll_id: str | None = "scroll-1") -> dict[str, Any]:
    body: dict[str, Any] = {"hits": {"hits": hits}}
    if scroll_id:
        body["_scroll_id"] = scroll_id
    return body


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://es.example.com:9243", "https://es.example.com:9243"),
            ("https://es.example.com/", "https://es.example.com"),
            ("es.example.com:9200", "https://es.example.com:9200"),
            (" http://es.internal:9200 ", "http://es.internal:9200"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "ftp://es.example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)


class TestAuthWiring:
    def test_api_key_auth_sets_header(self):
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="key123"))

        assert network.requests_log[0].headers["authorization"] == "ApiKey key123"

    def test_basic_auth_sets_session_auth(self):
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("https://es.example.com", ElasticsearchAuth(username="elastic", password="pw"))

        assert network.requests_log[0].headers["authorization"] == "Basic ZWxhc3RpYzpwdw=="


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (404, False, UNEXPECTED_RESPONSE_ERROR),
            (429, False, CLUSTER_UNAVAILABLE_ERROR),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected_valid, expected_error):
        response = ScriptedResponse(status=status_code, json={})
        script = always(response) if status_code in (429, 500) else [response]
        with scripted_network(script) as network:
            is_valid, error = validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="k"))

        assert is_valid is expected_valid
        assert error == expected_error
        assert {request.path for request in network.requests_log} == {"/"}

    @pytest.mark.parametrize(
        "raised, expected_error",
        [
            (Exception("boom"), UNREACHABLE_ERROR),
            (requests.exceptions.SSLError("bad cert"), TLS_ERROR),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_transport_failure_mapping(self, mock_session, raised, expected_error):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.side_effect = raised

        assert validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="k")) == (
            False,
            expected_error,
        )


class TestListIndices:
    def test_filters_system_indices_and_sorts(self):
        with scripted_network(
            [ScriptedResponse(json=[{"index": "orders"}, {"index": ".kibana"}, {"index": "accounts"}, {"index": ""}])]
        ) as network:
            indices = list_indices("https://es.example.com", ElasticsearchAuth(api_key="k"))

        assert indices == ["accounts", "orders"]
        assert network.requests_log[0].path == "/_cat/indices"

    def test_non_json_response_raises_clear_error(self):
        with scripted_network([ScriptedResponse(body=b"<html>")]):
            with pytest.raises(ValueError, match="non-JSON response"):
                list_indices("https://es.example.com", ElasticsearchAuth(api_key="k"))


class TestListDataStreams:
    def test_filters_hidden_system_and_dot_prefixed_streams_and_sorts(self):
        body = {
            "data_streams": [
                {"name": "metrics-app", "hidden": False, "system": False},
                {"name": "logs-web", "hidden": False, "system": False},
                {"name": "ilm-history-7", "hidden": True, "system": False},
                {"name": "fleet-actions", "hidden": False, "system": True},
                {"name": ".internal-stream", "hidden": False, "system": False},
                {"name": "", "hidden": False},
                {"hidden": False},
                "not-a-dict",
            ]
        }
        with scripted_network([ScriptedResponse(json=body)]) as network:
            streams = list_data_streams("https://es.example.com", ElasticsearchAuth(api_key="k"))

        assert streams == ["logs-web", "metrics-app"]
        assert network.requests_log[0].path == "/_data_stream"

    @pytest.mark.parametrize(
        "response",
        [
            # Clusters before 7.9 have no data stream API.
            ScriptedResponse(status=400, json={"error": {"type": "illegal_argument_exception"}}),
            ScriptedResponse(status=404, json={}),
            # Credentials without view_index_metadata can't list streams.
            ScriptedResponse(status=403, json={"error": {"type": "security_exception"}}),
            ScriptedResponse(body=b"<html>"),
            ScriptedResponse(json={"unexpected": True}),
            ScriptedResponse(json=[]),
        ],
    )
    def test_unavailable_api_yields_no_streams(self, response):
        with scripted_network([response]):
            assert list_data_streams("https://es.example.com", ElasticsearchAuth(api_key="k")) == []


class TestGetRows:
    def test_scrolls_until_short_page(self):
        full_hits = [{"_id": str(i), "_source": {"value": i}} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "orders",
            [
                _NOT_A_DATA_STREAM,
                ScriptedResponse(json={"orders": {"mappings": {"properties": {}}}}),
                ScriptedResponse(json=_scroll_page(full_hits)),
                ScriptedResponse(json=_scroll_page([{"_id": "last", "_source": {"value": -1}}])),
                ScriptedResponse(json={}),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.items[1] == [{"value": -1, "_id": "last"}]
        assert result.paths == [
            "/_data_stream/orders",
            "/orders/_mapping",
            "/orders/_search",
            "/_search/scroll",
            "/_search/scroll",
        ]
        assert result.requests[2].param("scroll") == "5m"
        assert result.requests[3].json() == {"scroll": "5m", "scroll_id": "scroll-1"}

    def test_scroll_context_is_cleared_after_walk(self):
        result = _driver().run(
            "orders",
            [
                _NOT_A_DATA_STREAM,
                ScriptedResponse(json={}),
                ScriptedResponse(json=_scroll_page([{"_id": "1", "_source": {}}])),
                ScriptedResponse(json={}),
            ],
        )

        assert result.raised is None
        assert [request.method for request in result.requests] == ["GET", "GET", "POST", "DELETE"]
        assert result.requests[3].path == "/_search/scroll"
        assert result.requests[3].json() == {"scroll_id": ["scroll-1"]}

    def test_float_typed_fields_are_coerced_across_rows(self):
        # A float-typed field whose docs mix whole (40) and fractional (40.5) values must all
        # arrive as floats so the column infers a single Arrow type; the long id stays an int.
        result = _driver().run(
            "orders",
            [
                _NOT_A_DATA_STREAM,
                ScriptedResponse(
                    json={"orders": {"mappings": {"properties": {"amount": {"type": "float"}, "id": {"type": "long"}}}}}
                ),
                ScriptedResponse(
                    json=_scroll_page(
                        [
                            {"_id": "1", "_source": {"amount": 40, "id": 100}},
                            {"_id": "2", "_source": {"amount": 40.5, "id": 200}},
                        ]
                    )
                ),
                ScriptedResponse(json={}),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [
                {"amount": 40.0, "id": 100, "_id": "1"},
                {"amount": 40.5, "id": 200, "_id": "2"},
            ]
        ]
        assert [type(row["amount"]) for row in result.rows] == [float, float]
        assert [type(row["id"]) for row in result.rows] == [int, int]

    def test_data_stream_rows_carry_backing_index(self):
        backing_mapping = {"properties": {"@timestamp": {"type": "date"}, "latency": {"type": "double"}}}
        result = _driver().run(
            "logs-web",
            [
                ScriptedResponse(json=_data_stream_body("logs-web")),
                ScriptedResponse(
                    json={
                        ".ds-logs-web-2099.01.01-000001": {"mappings": backing_mapping},
                        ".ds-logs-web-2099.01.02-000002": {"mappings": backing_mapping},
                    }
                ),
                ScriptedResponse(
                    json=_scroll_page(
                        [
                            {
                                "_index": ".ds-logs-web-2099.01.01-000001",
                                "_id": "same-id",
                                "_source": {"@timestamp": "2099-01-01T10:00:00Z", "latency": 3},
                            },
                            {
                                "_index": ".ds-logs-web-2099.01.02-000002",
                                "_id": "same-id",
                                "_source": {"@timestamp": "2099-01-02T10:00:00Z", "latency": 3.5},
                            },
                        ]
                    )
                ),
                ScriptedResponse(json={}),
            ],
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["_index", "_id"]
        assert result.rows == [
            {
                "@timestamp": "2099-01-01T10:00:00Z",
                "latency": 3.0,
                "_id": "same-id",
                "_index": ".ds-logs-web-2099.01.01-000001",
            },
            {
                "@timestamp": "2099-01-02T10:00:00Z",
                "latency": 3.5,
                "_id": "same-id",
                "_index": ".ds-logs-web-2099.01.02-000002",
            },
        ]
        assert result.paths[:3] == ["/_data_stream/logs-web", "/logs-web/_mapping", "/logs-web/_search"]


class TestFloatFieldPaths:
    @pytest.mark.parametrize(
        "mappings, expected",
        [
            # Scalar float types are collected; integer/keyword types are not.
            (
                {
                    "properties": {
                        "threshold_amount": {"type": "float"},
                        "total_hours_worked": {"type": "double"},
                        "ratio": {"type": "half_float"},
                        "price": {"type": "scaled_float", "scaling_factor": 100},
                        "id": {"type": "long"},
                        "count": {"type": "integer"},
                        "name": {"type": "keyword"},
                    }
                },
                {"threshold_amount", "total_hours_worked", "ratio", "price"},
            ),
            # Nested object properties are walked and reported as dotted paths.
            (
                {
                    "properties": {
                        "payroll": {
                            "properties": {
                                "rate": {"type": "double"},
                                "employee_id": {"type": "long"},
                            }
                        }
                    }
                },
                {"payroll.rate"},
            ),
            ({"properties": {}}, set()),
            ({}, set()),
        ],
    )
    def test_collects_float_typed_paths(self, mappings, expected):
        with scripted_network([ScriptedResponse(json={"orders": {"mappings": mappings}})]) as network:
            paths = get_float_field_paths(requests.Session(), "https://es.example.com", "orders")

        assert paths == expected
        assert network.requests_log[0].path == "/orders/_mapping"

    def test_unreadable_mapping_yields_no_paths(self):
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            paths = get_float_field_paths(requests.Session(), "https://es.example.com", "orders")

        assert paths == set()
        assert network.requests_log[0].path == "/orders/_mapping"


class TestCoerceFloatFields:
    @pytest.mark.parametrize(
        "doc, float_paths, expected",
        [
            # Whole numbers under float fields become floats; ints under non-float fields stay ints.
            (
                {"amount": 40, "id": 12345678901234567, "name": "x"},
                {"amount"},
                {"amount": 40.0, "id": 12345678901234567, "name": "x"},
            ),
            # Already-float values are untouched, missing paths are ignored.
            ({"amount": 40.5}, {"amount", "missing"}, {"amount": 40.5}),
            # Nested and array-of-scalar float fields are coerced element-wise.
            (
                {"payroll": {"rate": 20}, "readings": [1, 2, 3]},
                {"payroll.rate", "readings"},
                {"payroll": {"rate": 20.0}, "readings": [1.0, 2.0, 3.0]},
            ),
            # Arrays of nested objects are traversed.
            (
                {"lines": [{"cost": 5}, {"cost": 6}]},
                {"lines.cost"},
                {"lines": [{"cost": 5.0}, {"cost": 6.0}]},
            ),
            # Booleans are ints in Python but must not be coerced to float.
            ({"flag": True}, {"flag"}, {"flag": True}),
        ],
    )
    def test_coercion(self, doc, float_paths, expected):
        coerce_float_fields(doc, float_paths)
        assert doc == expected


class TestElasticsearchSourceResponse:
    @pytest.mark.parametrize(
        "detect_response, expected_primary_keys",
        [
            (_NOT_A_DATA_STREAM, ["_id"]),
            (ScriptedResponse(json=_data_stream_body("orders")), ["_index", "_id"]),
            # Only an exact name match counts as a data stream.
            (ScriptedResponse(json=_data_stream_body("orders-archive")), ["_id"]),
            # Credentials without view_index_metadata fall back to the plain index key.
            (ScriptedResponse(status=403, json={"error": {"type": "security_exception"}}), ["_id"]),
            (ScriptedResponse(body=b"<html>"), ["_id"]),
        ],
    )
    def test_response_metadata(self, detect_response, expected_primary_keys):
        with scripted_network([detect_response]) as network:
            response = elasticsearch_source(
                "https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock()
            )

        assert network.requests_log[0].path == "/_data_stream/orders"
        assert response.name == "orders"
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
