from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.elasticsearch import (
    PAGE_SIZE,
    ElasticsearchAuth,
    elasticsearch_source,
    get_rows,
    hostname_of,
    list_indices,
    normalize_host,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.elasticsearch"


def _response(body: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status
    resp.ok = status < 400
    return resp


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

    def test_hostname_of(self):
        assert hostname_of("https://es.example.com:9243/") == "es.example.com"


class TestAuthWiring:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_api_key_auth_sets_header(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="key123"))

        assert mock_session.return_value.headers["Authorization"] == "ApiKey key123"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_basic_auth_sets_session_auth(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("https://es.example.com", ElasticsearchAuth(username="elastic", password="pw"))

        assert mock_session.return_value.auth == ("elastic", "pw")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.return_value = _response({}, status=status_code)

        assert validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="k")) is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("https://es.example.com", ElasticsearchAuth(api_key="k")) is False


class TestListIndices:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_filters_system_indices_and_sorts(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.get.return_value = _response(
            [{"index": "orders"}, {"index": ".kibana"}, {"index": "accounts"}, {"index": ""}]
        )

        assert list_indices("https://es.example.com", ElasticsearchAuth(api_key="k")) == ["accounts", "orders"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_json_response_raises_clear_error(self, mock_session):
        mock_session.return_value.headers = {}
        response = _response(None)
        response.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        mock_session.return_value.get.return_value = response

        with pytest.raises(ValueError, match="non-JSON response"):
            list_indices("https://es.example.com", ElasticsearchAuth(api_key="k"))


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_scrolls_until_short_page(self, mock_session):
        mock_session.return_value.headers = {}
        full_hits = [{"_id": str(i), "_source": {"value": i}} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response(_scroll_page(full_hits)),
            _response(_scroll_page([{"_id": "last", "_source": {"value": -1}}])),
        ]

        batches = list(get_rows("https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock()))

        assert len(batches) == 2
        assert batches[1] == [{"value": -1, "_id": "last"}]
        urls = [call.args[0] for call in mock_session.return_value.post.call_args_list]
        assert urls[0].endswith("/orders/_search?scroll=5m")
        assert urls[1].endswith("/_search/scroll")
        body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert body == {"scroll": "5m", "scroll_id": "scroll-1"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_scroll_context_is_cleared_after_walk(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.post.return_value = _response(_scroll_page([{"_id": "1", "_source": {}}]))

        list(get_rows("https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock()))

        mock_session.return_value.delete.assert_called_once()
        assert mock_session.return_value.delete.call_args.kwargs["json"] == {"scroll_id": ["scroll-1"]}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_hoist_source_and_id(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.post.return_value = _response(
            _scroll_page([{"_id": "doc-1", "_source": {"name": "x"}}])
        )

        batches = list(get_rows("https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock()))

        assert batches == [[{"name": "x", "_id": "doc-1"}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_index_yields_nothing(self, mock_session):
        mock_session.return_value.headers = {}
        mock_session.return_value.post.return_value = _response(_scroll_page([]))

        assert (
            list(get_rows("https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock())) == []
        )


class TestElasticsearchSourceResponse:
    def test_response_metadata(self):
        response = elasticsearch_source(
            "https://es.example.com", ElasticsearchAuth(api_key="k"), "orders", mock.MagicMock()
        )

        assert response.name == "orders"
        assert response.primary_keys == ["_id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
