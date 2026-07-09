from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm import (
    OnepagecrmResumeConfig,
    _build_params,
    _to_epoch,
    get_rows,
    modified_since_anchor,
    onepagecrm_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ENDPOINTS,
    ONEPAGECRM_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm"


def _make_manager(resume_state: OnepagecrmResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = body
    return resp


def _list_page(
    data_key: str,
    item_key: str,
    records: list[dict[str, Any]],
    page: int,
    max_page: Optional[int],
) -> dict[str, Any]:
    return {
        "status": 0,
        "message": "OK",
        "data": {
            data_key: [{item_key: record} for record in records],
            "total_count": len(records),
            "page": page,
            "per_page": 100,
            "max_page": max_page,
        },
    }


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-timestamp", None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected

    def test_anchor_backs_off_one_second(self):
        assert modified_since_anchor(1700000000) == "1699999999"
        assert modified_since_anchor(None) is None


class TestBuildParams:
    def test_incremental_run_sorts_by_cursor_and_filters(self):
        params = _build_params(
            ONEPAGECRM_ENDPOINTS["contacts"], page=3, modified_since="1699999999", should_use_incremental_field=True
        )
        assert params == {
            "page": 3,
            "per_page": 100,
            "sort_by": "modified_at",
            "order": "asc",
            "modified_since": "1699999999",
        }

    def test_full_refresh_sorts_by_stable_creation_field(self):
        params = _build_params(
            ONEPAGECRM_ENDPOINTS["contacts"], page=1, modified_since=None, should_use_incremental_field=False
        )
        assert params == {"page": 1, "per_page": 100, "sort_by": "created_at", "order": "asc"}

    def test_unpaginated_config_endpoint_sends_no_params(self):
        params = _build_params(
            ONEPAGECRM_ENDPOINTS["users"], page=1, modified_since=None, should_use_incremental_field=False
        )
        assert params == {}


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_until_max_page_and_unwraps_records(self, mock_session):
        pages = [
            _list_page("contacts", "contact", [{"id": "a1"}, {"id": "a2"}], page=1, max_page=2),
            _list_page("contacts", "contact", [{"id": "a3"}], page=2, max_page=2),
        ]
        mock_session.return_value.get.side_effect = [_response(p) for p in pages]

        manager = _make_manager()
        batches = list(get_rows("uid", "key", "contacts", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["a1", "a2", "a3"]
        assert mock_session.return_value.get.call_count == 2
        manager.save_state.assert_called_once_with(OnepagecrmResumeConfig(page=2, modified_since=None))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_incremental_run_pins_anchor_across_pages(self, mock_session):
        pages = [
            _list_page("deals", "deal", [{"id": "d1"}], page=1, max_page=2),
            _list_page("deals", "deal", [{"id": "d2"}], page=2, max_page=2),
        ]
        mock_session.return_value.get.side_effect = [_response(p) for p in pages]

        manager = _make_manager()
        list(
            get_rows(
                "uid",
                "key",
                "deals",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        for call in mock_session.return_value.get.call_args_list:
            assert call.kwargs["params"]["modified_since"] == "1699999999"
        manager.save_state.assert_called_once_with(OnepagecrmResumeConfig(page=2, modified_since="1699999999"))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_page_and_saved_anchor(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            _list_page("deals", "deal", [{"id": "d9"}], page=5, max_page=5)
        )
        manager = _make_manager(OnepagecrmResumeConfig(page=5, modified_since="1600000000"))

        list(
            get_rows(
                "uid",
                "key",
                "deals",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                # A fresher watermark must NOT replace the saved anchor: page numbers are only
                # stable for the query the run started with.
                db_incremental_field_last_value=1700000000,
            )
        )

        params = mock_session.return_value.get.call_args.kwargs["params"]
        assert params["page"] == 5
        assert params["modified_since"] == "1600000000"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_short_page_terminates_when_max_page_missing(self, mock_session):
        body = _list_page("contacts", "contact", [{"id": "a1"}], page=1, max_page=None)
        body["data"].pop("max_page")
        mock_session.return_value.get.return_value = _response(body)

        manager = _make_manager()
        batches = list(get_rows("uid", "key", "contacts", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["a1"]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_first_page_stops_without_state(self, mock_session):
        mock_session.return_value.get.return_value = _response(_list_page("contacts", "contact", [], 1, 1))

        manager = _make_manager()
        assert list(get_rows("uid", "key", "contacts", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint, body, expected_ids",
        [
            ("users", {"data": [{"user": {"id": "u1"}}, {"user": {"id": "u2"}}]}, ["u1", "u2"]),
            ("statuses", {"data": [{"status": {"id": "s1"}}]}, ["s1"]),
            ("lead_sources", {"data": [{"id": "advertisement"}, {"id": "web"}]}, ["advertisement", "web"]),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_config_endpoints_yield_bare_array_records(self, mock_session, endpoint, body, expected_ids):
        mock_session.return_value.get.return_value = _response(body)

        manager = _make_manager()
        batches = list(get_rows("uid", "key", endpoint, mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == expected_ids
        assert mock_session.return_value.get.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid OnePageCRM user ID or API key"),
            (403, False, "Invalid OnePageCRM user ID or API key"),
            (500, False, "OnePageCRM returned HTTP 500"),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        valid, message = validate_credentials("uid", "key")

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_connection_error_reports_failure(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        valid, message = validate_credentials("uid", "key")

        assert valid is False
        assert message is not None and "Could not connect to OnePageCRM" in message


class TestOnepagecrmSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ONEPAGECRM_ENDPOINTS[endpoint]
        response = onepagecrm_source("uid", "key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", [c for c in ONEPAGECRM_ENDPOINTS.values() if c.partition_key])
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "created_at"
