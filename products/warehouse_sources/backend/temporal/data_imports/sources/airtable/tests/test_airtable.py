import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable import (
    _format_created_time,
    airtable_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import (
    AIRTABLE_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the airtable module.
AIRTABLE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT PREPARE time.

    ``request.params`` is mutated in place across pages, so snapshot a copy when each request is
    prepared instead of inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, **kwargs: Any):
    return airtable_source("pat", endpoint, team_id=1, job_id="j", **kwargs)


class TestFormatCreatedTime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_created_time(value) == expected


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
    @mock.patch(AIRTABLE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("pat") is expected

    @mock.patch(AIRTABLE_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("pat") is False


class TestBases:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_offset_token(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}], "offset": "off1"}),
                _response({"bases": [{"id": "app2"}]}),
            ],
        )

        rows = _rows(_source("bases"))

        assert [r["id"] for r in rows] == ["app1", "app2"]
        # First page carries no offset; the second resumes from the returned cursor.
        assert "offset" not in snapshots[0]["params"]
        assert snapshots[1]["params"]["offset"] == "off1"


class TestTables:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_bases_and_injects_base_id(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}, {"id": "app2"}]}),
                _response({"tables": [{"id": "tbl1", "name": "Tasks"}]}),
                _response({"tables": [{"id": "tbl2", "name": "Leads"}]}),
            ],
        )

        rows = _rows(_source("tables"))

        assert [(t["id"], t["_base_id"]) for t in rows] == [("tbl1", "app1"), ("tbl2", "app2")]
        # No leaked include_from_parent scaffolding key.
        assert all("_bases_id" not in t for t in rows)
        assert urlparse(snapshots[1]["url"]).path == "/v0/meta/bases/app1/tables"
        assert urlparse(snapshots[2]["url"]).path == "/v0/meta/bases/app2/tables"


class TestRecords:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_tables_and_paginates_records(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}]}),
                _response({"tables": [{"id": "tbl1"}]}),
                _response({"records": [{"id": "rec1", "createdTime": "2024-01-01T00:00:00.000Z"}], "offset": "off1"}),
                _response({"records": [{"id": "rec2", "createdTime": "2024-01-02T00:00:00.000Z"}]}),
            ],
        )

        rows = _rows(_source("records"))

        assert [(r["id"], r["_base_id"], r["_table_id"]) for r in rows] == [
            ("rec1", "app1", "tbl1"),
            ("rec2", "app1", "tbl1"),
        ]
        # No leaked include_from_parent scaffolding keys.
        assert all("_tables__base_id" not in r and "_tables_id" not in r for r in rows)
        assert urlparse(snapshots[2]["url"]).path == "/v0/app1/tbl1"
        assert snapshots[2]["params"]["pageSize"] == 100
        assert snapshots[3]["params"]["offset"] == "off1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_records_filter_on_created_time(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}]}),
                _response({"tables": [{"id": "tbl1"}]}),
                _response({"records": []}),
            ],
        )

        _rows(
            _source(
                "records",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[2]["params"]["filterByFormula"] == 'IS_AFTER(CREATED_TIME(), "2024-01-02T00:00:00.000Z")'

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_filter(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}]}),
                _response({"tables": [{"id": "tbl1"}]}),
                _response({"records": []}),
            ],
        )

        _rows(_source("records"))

        assert "filterByFormula" not in snapshots[2]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_table_without_id_fails_loudly(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"bases": [{"id": "app1"}]}),
                _response({"tables": [{"name": "broken"}]}),
            ],
        )

        # A table row missing its id can't bind the {table_id} path param — fail loud, don't skip it.
        with pytest.raises(ValueError, match="table_id"):
            _rows(_source("records"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_everything_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"bases": []})])

        assert _rows(_source("records")) == []


class TestAirtableSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = AIRTABLE_ENDPOINTS[endpoint]
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_records_have_composite_primary_key(self, MockSession):
        response = _source("records")
        assert response.primary_keys == ["_base_id", "_table_id", "id"]
