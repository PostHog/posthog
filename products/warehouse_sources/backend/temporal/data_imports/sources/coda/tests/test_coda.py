import json
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda import coda_source, validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import CODA_ENDPOINTS, ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the coda module.
CODA_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda.make_tracked_session"


def _response(items: list[dict[str, Any]], next_token: str | None = None) -> Response:
    body: dict[str, Any] = {"items": items}
    if next_token:
        body["nextPageToken"] = next_token
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, capturing each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    request_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        request_snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return request_snapshots


def _rows(endpoint: str) -> list[dict[str, Any]]:
    response = coda_source("token", endpoint, team_id=1, job_id="j")
    return [row for page in response.items() for row in page]


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
    @mock.patch(CODA_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(CODA_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_docs_paginate_via_page_token(self, MockSession):
        requests = _wire(
            MockSession.return_value,
            [_response([{"id": "doc1"}], next_token="tok1"), _response([{"id": "doc2"}])],
        )

        rows = _rows("docs")

        assert [r["id"] for r in rows] == ["doc1", "doc2"]
        # The next page echoes the body's nextPageToken back as the pageToken query param.
        assert requests[1]["params"]["pageToken"] == "tok1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_intermediate_page_does_not_halt_pagination(self, MockSession):
        _wire(
            MockSession.return_value,
            [
                _response([{"id": "doc1"}], next_token="tok1"),
                _response([], next_token="tok2"),
                _response([{"id": "doc2"}]),
            ],
        )

        rows = _rows("docs")

        assert [r["id"] for r in rows] == ["doc1", "doc2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tables_fan_out_over_docs(self, MockSession):
        requests = _wire(
            MockSession.return_value,
            [_response([{"id": "doc1"}]), _response([{"id": "grid-1", "name": "Tasks"}])],
        )

        rows = _rows("tables")

        assert [(t["id"], t["_doc_id"]) for t in rows] == [("grid-1", "doc1")]
        assert urlparse(requests[1]["url"]).path == "/apis/v1/docs/doc1/tables"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_fan_out_docs_tables_rows(self, MockSession):
        requests = _wire(
            MockSession.return_value,
            [
                _response([{"id": "doc1"}]),  # docs
                _response([{"id": "grid-1"}]),  # tables for doc1
                _response([{"id": "i-1", "values": {"Name": "x"}}]),  # rows for grid-1
            ],
        )

        rows = _rows("rows")

        assert [(r["id"], r["_doc_id"], r["_table_id"]) for r in rows] == [("i-1", "doc1", "grid-1")]
        parsed = urlparse(requests[2]["url"])
        assert parsed.path == "/apis/v1/docs/doc1/tables/grid-1/rows"
        assert requests[2]["params"]["useColumnNames"] == "true"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_table_without_id_fails_fast_in_rows(self, MockSession):
        _wire(
            MockSession.return_value,
            [_response([{"id": "doc1"}]), _response([{"name": "broken"}])],
        )

        # A table row missing its primary key can't be bound into the rows path — fail loud
        # rather than silently dropping the table.
        with pytest.raises(ValueError, match="expects a field 'id'"):
            _rows("rows")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_workspace_yields_nothing(self, MockSession):
        MockSession.return_value.headers = {}
        MockSession.return_value.prepare_request.side_effect = lambda request: mock.MagicMock()
        MockSession.return_value.send.return_value = _response([])

        assert _rows("rows") == []

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Coda endpoint"):
            coda_source("token", "nonsense", team_id=1, job_id="j")


class TestCodaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CODA_ENDPOINTS[endpoint]
        response = coda_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_rows_have_composite_primary_key(self):
        response = coda_source("token", "rows", team_id=1, job_id="j")
        assert response.primary_keys == ["_doc_id", "_table_id", "id"]
