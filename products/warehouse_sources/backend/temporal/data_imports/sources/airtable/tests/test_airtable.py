from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable import (
    _format_created_time,
    airtable_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import (
    AIRTABLE_ENDPOINTS,
    ENDPOINTS,
)


def _response(body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.time.sleep"):
        yield


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
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("pat") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("pat") is False


class TestGetRowsBases:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_paginates_via_offset_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"bases": [{"id": "app1"}], "offset": "off1"}),
            _response({"bases": [{"id": "app2"}]}),
        ]

        batches = list(get_rows("pat", "bases", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["app1", "app2"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["offset"] == ["off1"]


class TestGetRowsTables:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_fans_out_over_bases_and_injects_base_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"bases": [{"id": "app1"}, {"id": "app2"}]}),
            _response({"tables": [{"id": "tbl1", "name": "Tasks"}]}),
            _response({"tables": [{"id": "tbl2", "name": "Leads"}]}),
        ]

        batches = list(get_rows("pat", "tables", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(t["id"], t["_base_id"]) for t in flat] == [("tbl1", "app1"), ("tbl2", "app2")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[1]).path == "/v0/meta/bases/app1/tables"
        assert urlparse(urls[2]).path == "/v0/meta/bases/app2/tables"


class TestGetRowsRecords:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_fans_out_over_tables_and_paginates_records(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"bases": [{"id": "app1"}]}),
            _response({"tables": [{"id": "tbl1"}]}),
            _response({"records": [{"id": "rec1", "createdTime": "2024-01-01T00:00:00.000Z"}], "offset": "off1"}),
            _response({"records": [{"id": "rec2", "createdTime": "2024-01-02T00:00:00.000Z"}]}),
        ]

        batches = list(get_rows("pat", "records", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(r["id"], r["_base_id"], r["_table_id"]) for r in flat] == [
            ("rec1", "app1", "tbl1"),
            ("rec2", "app1", "tbl1"),
        ]
        record_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list[2:]]
        assert urlparse(record_urls[0]).path == "/v0/app1/tbl1"
        assert parse_qs(urlparse(record_urls[1]).query)["offset"] == ["off1"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_incremental_records_filter_on_created_time(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"bases": [{"id": "app1"}]}),
            _response({"tables": [{"id": "tbl1"}]}),
            _response({"records": []}),
        ]

        list(
            get_rows(
                "pat",
                "records",
                mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        record_url = mock_session.return_value.get.call_args_list[2].args[0]
        formula = parse_qs(urlparse(record_url).query)["filterByFormula"][0]
        assert formula == 'IS_AFTER(CREATED_TIME(), "2024-01-02T00:00:00.000Z")'

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_table_without_id_fails_loudly(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"bases": [{"id": "app1"}]}),
            _response({"tables": [{"name": "broken"}]}),
        ]

        with pytest.raises(KeyError):
            list(get_rows("pat", "records", mock.MagicMock()))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable.make_tracked_session"
    )
    def test_empty_everything_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response({"bases": []})

        assert list(get_rows("pat", "records", mock.MagicMock())) == []


class TestAirtableSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = AIRTABLE_ENDPOINTS[endpoint]
        response = airtable_source("pat", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_records_have_composite_primary_key(self):
        response = airtable_source("pat", "records", mock.MagicMock())
        assert response.primary_keys == ["_base_id", "_table_id", "id"]
