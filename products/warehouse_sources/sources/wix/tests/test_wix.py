from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.wix.wix import (
    WixResumeConfig,
    _to_wix_datetime,
    check_endpoint_permissions,
    get_rows,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.sources.wix.wix"


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
    def test_repeated_cursor_raises_instead_of_paging_forever(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(payload=_page([{"id": "1"}], "orders", "metadata", "cursor-2")),
            _response(payload=_page([{"id": "2"}], "orders", "metadata", "cursor-2")),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            with pytest.raises(RuntimeError, match="repeated cursor"):
                list(get_rows("key", "site", "orders", mock.MagicMock(), _manager()))

        assert session.post.call_count == 2

    @pytest.mark.parametrize(
        "endpoint,data_key,cursors_key,expected_field",
        [
            ("orders", "orders", "metadata", "updatedDate"),
            ("store_categories", "categories", "pagingMetadata", "updatedDate"),
            ("bookings", "extendedBookings", "pagingMetadata", "booking.updatedDate"),
        ],
    )
    def test_incremental_run_filters_and_sorts_on_the_chosen_field(
        self, endpoint: str, data_key: str, cursors_key: str, expected_field: str
    ) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(payload=_page([], data_key, cursors_key, None))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(
                get_rows(
                    "key",
                    "site",
                    endpoint,
                    mock.MagicMock(),
                    _manager(),
                    incremental_field="updatedDate",
                    db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                )
            )

        body = next(iter(session.post.call_args.kwargs["json"].values()))
        assert body["filter"] == {expected_field: {"$gte": "2026-01-02T03:04:05Z"}}
        assert body["sort"] == [{"fieldName": expected_field, "order": "ASC"}]

    def test_store_categories_send_the_tree_reference_on_every_page(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(payload=_page([{"id": "1"}], "categories", "pagingMetadata", "cursor-2")),
            _response(payload=_page([{"id": "2"}], "categories", "pagingMetadata", None)),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "store_categories", mock.MagicMock(), _manager()))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        for call in session.post.call_args_list:
            assert call.kwargs["json"]["treeReference"] == {"appNamespace": "@wix/stores"}
            assert call.kwargs["json"]["returnNonVisibleCategories"] is True
        assert session.post.call_args_list[1].kwargs["json"]["query"] == {
            "cursorPaging": {"limit": 100, "cursor": "cursor-2"}
        }

    def test_bookings_lift_the_booking_record_to_the_row_root(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(
            payload=_page(
                [
                    {"booking": {"id": "b1", "status": "CONFIRMED"}, "attendance": {"status": "ATTENDED"}},
                    {"booking": None},
                ],
                "extendedBookings",
                "pagingMetadata",
                None,
            )
        )

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "bookings", mock.MagicMock(), _manager()))

        assert batches == [[{"id": "b1", "status": "CONFIRMED", "attendance": {"status": "ATTENDED"}}, {}]]

    @pytest.mark.parametrize(
        "page_sizes,expected_offsets",
        [
            ([100, 3], [0, 100]),
            ([100, 100, 0], [0, 100, 200]),
            ([0], [0]),
        ],
    )
    def test_blog_categories_page_by_offset_until_a_short_page(
        self, page_sizes: list[int], expected_offsets: list[int]
    ) -> None:
        session = mock.MagicMock()
        offsets: list[int] = []

        def respond(url: str, json: dict[str, Any], timeout: int) -> mock.MagicMock:
            offsets.append(json["query"]["paging"]["offset"])
            size = page_sizes[len(offsets) - 1]
            return _response(payload={"categories": [{"id": f"{len(offsets)}-{i}"} for i in range(size)]})

        session.post.side_effect = respond

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "blog_categories", mock.MagicMock(), _manager()))

        assert offsets == expected_offsets
        assert [len(batch) for batch in batches] == [size for size in page_sizes if size]

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
        response = _response(status_code=400)
        response.text = "potentially sensitive upstream error"
        session.post.return_value = response
        logger = mock.MagicMock()

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "site", "orders", logger, _manager()))

        assert "potentially sensitive upstream error" not in str(logger.error.call_args)

    def test_order_transactions_look_up_each_page_of_orders(self) -> None:
        session = mock.MagicMock()
        manager = _manager()

        def respond(url: str, json: dict[str, Any], timeout: int) -> mock.MagicMock:
            if url.endswith("/ecom/v1/orders/search"):
                if "cursor" in json["search"]["cursorPaging"]:
                    return _response(
                        payload=_page([{"id": "o3", "createdDate": "2026-01-03"}], "orders", "metadata", None)
                    )
                return _response(
                    payload=_page(
                        [{"id": "o1", "createdDate": "2026-01-01"}, {"id": "o2", "createdDate": "2026-01-02"}],
                        "orders",
                        "metadata",
                        "cursor-2",
                    )
                )
            assert url.endswith("/ecom/v1/payments/list-by-ids")
            if json["orderIds"] == ["o3"]:
                return _response(payload={"orderTransactions": []})
            return _response(
                payload={
                    "orderTransactions": [
                        {"orderId": "o1", "payments": [{"id": "p1"}], "refunds": []},
                        {"orderId": "o2", "payments": [], "refunds": [{"id": "r1"}]},
                    ]
                }
            )

        session.post.side_effect = respond

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            batches = list(get_rows("key", "site", "order_transactions", mock.MagicMock(), manager))

        assert batches == [
            [
                {"orderId": "o1", "payments": [{"id": "p1"}], "refunds": [], "orderCreatedDate": "2026-01-01"},
                {"orderId": "o2", "payments": [], "refunds": [{"id": "r1"}], "orderCreatedDate": "2026-01-02"},
            ]
        ]
        lookups = [call.kwargs["json"] for call in session.post.call_args_list if "orderIds" in call.kwargs["json"]]
        assert lookups == [{"orderIds": ["o1", "o2"]}, {"orderIds": ["o3"]}]
        manager.save_state.assert_called_once_with(WixResumeConfig(cursor="cursor-2"))
        manager.safe_point.assert_called_once()


class TestWixCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid,expected_message_start",
        [
            (200, True, None),
            (403, True, None),
            (401, False, "Wix rejected this API key."),
            (404, False, "Wix could not find this site."),
            (428, False, "Wix could not find this site."),
            (500, False, "Wix couldn't check your API key."),
            (502, False, "Wix couldn't check your API key."),
        ],
    )
    def test_status_maps_to_a_verdict(
        self, status_code: int, expected_valid: bool, expected_message_start: str | None
    ) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=status_code)

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("key", "site")

        assert valid is expected_valid
        if expected_message_start is None:
            assert message is None
        else:
            assert message is not None and message.startswith(expected_message_start)
            assert str(status_code) not in message

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

    @pytest.mark.parametrize(
        "endpoint,expected_path,expected_body",
        [
            ("order_transactions", "/ecom/v1/orders/search", {"search": {"cursorPaging": {"limit": 1}}}),
            ("blog_categories", "/blog/v3/categories/query", {"query": {"paging": {"limit": 1}}}),
            (
                "store_categories",
                "/categories/v1/categories/query",
                {
                    "query": {"cursorPaging": {"limit": 1}},
                    "treeReference": {"appNamespace": "@wix/stores"},
                    "returnNonVisibleCategories": True,
                },
            ),
        ],
    )
    def test_permission_probe_sends_a_request_the_endpoint_accepts(
        self, endpoint: str, expected_path: str, expected_body: dict[str, Any]
    ) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=200)

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            check_endpoint_permissions("key", "site", [endpoint])

        assert session.post.call_args.args[0] == f"https://www.wixapis.com{expected_path}"
        assert session.post.call_args.kwargs["json"] == expected_body


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
