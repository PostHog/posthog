from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda import (
    coda_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import CODA_ENDPOINTS, ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda"


def _response(items: list[dict[str, Any]], next_token: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"items": items}
    if next_token:
        body["nextPageToken"] = next_token
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch(f"{_MODULE}.time.sleep"):
        yield


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
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_docs_paginate_via_page_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "doc1"}], next_token="tok1"),
            _response([{"id": "doc2"}]),
        ]

        batches = list(get_rows("token", "docs", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["doc1", "doc2"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["pageToken"] == ["tok1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_intermediate_page_does_not_halt_pagination(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "doc1"}], next_token="tok1"),
            _response([], next_token="tok2"),
            _response([{"id": "doc2"}]),
        ]

        batches = list(get_rows("token", "docs", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["doc1", "doc2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_tables_fan_out_over_docs(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "doc1"}]),
            _response([{"id": "grid-1", "name": "Tasks"}]),
        ]

        batches = list(get_rows("token", "tables", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(t["id"], t["_doc_id"]) for t in flat] == [("grid-1", "doc1")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[1]).path == "/apis/v1/docs/doc1/tables"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_fan_out_docs_tables_rows(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "doc1"}]),  # docs
            _response([{"id": "grid-1"}]),  # tables for doc1
            _response([{"id": "i-1", "values": {"Name": "x"}}]),  # rows for grid-1
        ]

        batches = list(get_rows("token", "rows", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(r["id"], r["_doc_id"], r["_table_id"]) for r in flat] == [("i-1", "doc1", "grid-1")]
        rows_url = mock_session.return_value.get.call_args_list[2].args[0]
        parsed = urlparse(rows_url)
        assert parsed.path == "/apis/v1/docs/doc1/tables/grid-1/rows"
        assert parse_qs(parsed.query)["useColumnNames"] == ["true"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_table_without_id_fails_fast_in_rows(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "doc1"}]),
            _response([{"name": "broken"}]),
        ]

        with pytest.raises(KeyError):
            list(get_rows("token", "rows", mock.MagicMock()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_workspace_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        assert list(get_rows("token", "rows", mock.MagicMock())) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unknown_endpoint_raises(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        with pytest.raises(ValueError, match="Unknown Coda endpoint"):
            list(get_rows("token", "nonsense", mock.MagicMock()))


class TestCodaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CODA_ENDPOINTS[endpoint]
        response = coda_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_rows_have_composite_primary_key(self):
        response = coda_source("token", "rows", mock.MagicMock())
        assert response.primary_keys == ["_doc_id", "_table_id", "id"]
