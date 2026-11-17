from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.xendit._config import XenditSourceConfig
from products.warehouse_sources.sources.xendit.settings import XENDIT_BASE_URL, XENDIT_ENDPOINTS
from products.warehouse_sources.sources.xendit.source import XenditSource
from products.warehouse_sources.sources.xendit.xendit import (
    XenditResumeConfig,
    _build_params,
    _format_datetime,
    validate_credentials,
)


def _response(items: list[dict[str, Any]] | None, has_more: bool, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"data": items or [], "has_more": has_more, "links": []})


def _cursor_of(page: dict[str, Any]) -> str:
    return page.get("next_cursor") or page["pagination"]["next_cursor"]


def _driver() -> SourceDriver:
    return SourceDriver(XenditSource(), XenditSourceConfig(api_key="xnd_key"))


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)

        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    @pytest.mark.parametrize("incremental_field", [None, "estimated_settlement_time"])
    def test_unfilterable_cursor_field_falls_back_to_updated(self, incremental_field: str | None) -> None:
        # A field Xendit does not filter on server-side would be silently ignored, turning the
        # sync into a full refresh that claims to be incremental.
        params = _build_params(
            XENDIT_ENDPOINTS["transactions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=incremental_field,
        )

        assert params["updated[gte]"] == "2026-03-04T02:58:14.000Z"
        assert "estimated_settlement_time[gte]" not in params


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected_valid", [(403, False)])
    def test_status_is_reported_back(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            reachable, status = validate_credentials("xnd_key", "/transactions")

        assert (reachable, status) == (expected_valid, status_code)
        request = network.requests_log[0]
        assert request.url == f"{XENDIT_BASE_URL}/transactions?limit=1"
        assert "for-user-id" not in request.headers


class TestPagination:
    def test_stops_when_the_cursor_does_not_advance(self) -> None:
        # An API that keeps claiming has_more while returning the same last row would otherwise
        # be refetched until the activity times out.
        result = _driver().run(
            "transactions",
            [
                _response([{"id": "txn_1"}], has_more=True),
                _response([{"id": "txn_1"}], has_more=True),
            ],
        )

        assert [row["id"] for row in result.rows] == ["txn_1", "txn_1"]
        assert len(result.requests) == 2

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "transactions",
            [_response([{"id": "txn_9"}], has_more=False)],
            resume_state=XenditResumeConfig(after_id="txn_8"),
        )

        assert [row["id"] for row in result.rows] == ["txn_9"]
        assert result.requests[0].param("after_id") == "txn_8"

    def test_incremental_filter_rides_the_first_request(self) -> None:
        result = _driver().run(
            "transactions",
            [_response([{"id": "txn_1"}], has_more=False)],
            incremental_field="updated",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.requests[0].param("updated[gte]") == "2026-03-04T02:58:14.000Z"

    @pytest.mark.parametrize(
        "endpoint, pages, expected_limit",
        [
            (
                "disputes",
                [
                    {"data": [{"id": "dspt_1"}], "pagination": {"next_cursor": "dspt_1", "has_more": True}},
                    {"data": [{"id": "dspt_2"}], "pagination": {"next_cursor": "dspt_2", "has_more": True}},
                    {"data": [{"id": "dspt_3"}], "pagination": {"next_cursor": None, "has_more": False}},
                ],
                "100",
            ),
            (
                "bill_payment_products",
                [
                    {"data": [{"id": "PLN_20K"}], "limit": 50, "next_cursor": "c1=="},
                    {"data": [{"id": "PLN_50K"}], "limit": 50, "next_cursor": "c2=="},
                    {"data": [{"id": "PLN_100K"}], "limit": 50, "next_cursor": ""},
                ],
                "50",
            ),
        ],
    )
    def test_body_cursor_walks_to_the_terminal_page(
        self, endpoint: str, pages: list[dict[str, Any]], expected_limit: str
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(status=200, json=page) for page in pages])

        assert len(result.rows) == 3
        assert len(result.requests) == 3
        assert [request.param("cursor") for request in result.requests] == [
            None,
            *[_cursor_of(page) for page in pages[:-1]],
        ]
        assert all(request.param("after_id") is None for request in result.requests)
        assert result.requests[0].param("limit") == expected_limit

    def test_forbidden_response_raises(self) -> None:
        result = _driver().run("transactions", [_response(None, has_more=False, status=403)])

        assert isinstance(result.raised, requests.HTTPError)
