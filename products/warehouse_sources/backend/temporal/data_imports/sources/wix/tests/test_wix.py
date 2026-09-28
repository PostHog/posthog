from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.wix.settings import WIX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wix.wix import (
    PAGE_SIZE,
    WixResumeConfig,
    _to_wix_datetime,
    check_endpoint_permissions,
    get_rows,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.wix.wix"


def _manager(resume_state: WixResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(
    status_code: int = 200,
    payload: Optional[dict[str, Any]] = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload or {}
    response.text = ""
    if status_code >= 400:
        error = requests.HTTPError(f"{status_code} Client Error", response=response)
        response.raise_for_status.side_effect = error
    return response


def _page(items: list[dict[str, Any]], data_key: str, cursors_key: str, next_cursor: str | None) -> dict[str, Any]:
    return {
        data_key: items,
        cursors_key: {"cursors": {"next": next_cursor}, "hasNext": next_cursor is not None},
    }


class TestWixTransport:
    def test_walks_cursor_pages_until_the_api_stops_returning_one(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(payload=_page([{"id": "1"}], "orders", "metadata", "cursor-2")),
            _response(payload=_page([{"id": "2"}], "orders", "metadata", None)),
        ]
        manager = _manager()

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "orders", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert session.post.call_count == 2

    def test_follow_up_pages_send_the_cursor_without_filter_or_sort(self) -> None:
        # Wix encodes the filter and sort into the cursor and rejects a request that repeats them.
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(payload=_page([{"id": "1"}], "orders", "metadata", "cursor-2")),
            _response(payload=_page([{"id": "2"}], "orders", "metadata", None)),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("key", "site", "orders", mock.MagicMock(), _manager()))

        second_body = session.post.call_args_list[1].kwargs["json"]["search"]
        assert second_body == {"cursorPaging": {"limit": PAGE_SIZE, "cursor": "cursor-2"}}

    def test_incremental_run_filters_and_sorts_on_the_chosen_field(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(payload=_page([], "orders", "metadata", None))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(
                get_rows(
                    "key",
                    "site",
                    "orders",
                    mock.MagicMock(),
                    _manager(),
                    incremental_field="updatedDate",
                    db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                )
            )

        body = session.post.call_args.kwargs["json"]["search"]
        assert body["filter"] == {"updatedDate": {"$gte": "2026-01-02T03:04:05Z"}}
        assert body["sort"] == [{"fieldName": "updatedDate", "order": "ASC"}]

    def test_full_refresh_run_sends_no_watermark_filter(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(payload=_page([], "orders", "metadata", None))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("key", "site", "orders", mock.MagicMock(), _manager()))

        body = session.post.call_args.kwargs["json"]["search"]
        assert "filter" not in body
        assert body["sort"] == [{"fieldName": "createdDate", "order": "ASC"}]

    def test_resumes_from_the_saved_cursor(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(payload=_page([{"id": "9"}], "orders", "metadata", None))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("key", "site", "orders", mock.MagicMock(), _manager(WixResumeConfig(cursor="saved"))))

        body = session.post.call_args.kwargs["json"]["search"]
        assert body["cursorPaging"]["cursor"] == "saved"

    def test_expired_resume_cursor_restarts_the_stream(self) -> None:
        # Wix cursors are time-limited, so a resumed run can open with one the API no longer accepts.
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(status_code=400),
            _response(payload=_page([{"id": "1"}], "orders", "metadata", None)),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "orders", mock.MagicMock(), _manager(WixResumeConfig("stale"))))

        assert batches == [[{"id": "1"}]]
        retried_body = session.post.call_args_list[1].kwargs["json"]["search"]
        assert "cursor" not in retried_body["cursorPaging"]

    def test_a_400_on_the_first_page_is_not_swallowed(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=400)

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "site", "orders", mock.MagicMock(), _manager()))

    def test_state_is_saved_for_each_page_that_has_a_successor(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(payload=_page([{"id": "1"}], "orders", "metadata", "cursor-2")),
            _response(payload=_page([{"id": "2"}], "orders", "metadata", None)),
        ]
        manager = _manager()

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("key", "site", "orders", mock.MagicMock(), manager))

        assert manager.save_state.call_args_list == [mock.call(WixResumeConfig(cursor="cursor-2"))]

    @pytest.mark.parametrize("endpoint", sorted(WIX_ENDPOINTS))
    def test_every_endpoint_reads_rows_from_its_own_envelope(self, endpoint: str) -> None:
        config = WIX_ENDPOINTS[endpoint]
        session = mock.MagicMock()
        session.post.return_value = _response(payload=_page([{"id": "1"}], config.data_key, config.cursors_key, None))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", endpoint, mock.MagicMock(), _manager()))

        assert batches == [[{"id": "1"}]]
        assert session.post.call_args.kwargs["json"].keys() == {config.body_key}


class TestWixCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (403, True), (401, False), (428, False), (500, False)],
    )
    def test_status_maps_to_a_verdict(self, status_code: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=status_code)

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("key", "site")

        assert valid is expected_valid
        assert (message is None) is expected_valid

    def test_unreachable_api_is_reported_rather_than_raised(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("no route")

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("key", "site")

        assert valid is False
        assert message is not None

    def test_permission_probe_names_the_missing_wix_permission(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [_response(status_code=403), _response(status_code=200)]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            results = check_endpoint_permissions("key", "site", ["orders", "contacts"])

        assert results["orders"] == "This API key is missing the 'Read eCommerce Orders' permission in Wix."
        assert results["contacts"] is None

    def test_permission_probe_keeps_a_table_selectable_when_the_request_fails(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("no route")

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            assert check_endpoint_permissions("key", "site", ["orders"]) == {"orders": None}


class TestWixTimestamps:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC), "2026-05-06T07:08:09Z"),
            (datetime(2026, 5, 6, 7, 8, 9), "2026-05-06T07:08:09Z"),
            ("2026-05-06T07:08:09Z", "2026-05-06T07:08:09Z"),
            (None, None),
        ],
    )
    def test_values_render_as_rfc_3339(self, value: Any, expected: str | None) -> None:
        assert _to_wix_datetime(value) == expected
