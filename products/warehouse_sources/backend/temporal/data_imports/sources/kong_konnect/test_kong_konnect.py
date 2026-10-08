from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import kong_konnect
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    CONTROL_PLANES_PAGE_SIZE,
    MAX_PAGE_SIZE,
    KongKonnectResumeConfig,
    _clamp_future_value_to_now,
    _format_datetime,
    _resolve_window,
    get_lookup_rows,
    get_rows,
    kong_konnect_source,
    validate_credentials,
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestResolveWindow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_watermark_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise produce start > end, wedging every later sync.
        start, _ = _resolve_window(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
            lookback_days=30,
        )
        assert start == "2026-06-15T12:00:00Z"


class TestClampFutureValue:
    @parameterized.expand(
        [
            ("past_datetime_untouched", datetime(2026, 1, 1, tzinfo=UTC), False),
            ("future_datetime_clamped", datetime(2027, 1, 1, tzinfo=UTC), True),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_clamp(self, _name: str, value: datetime, should_clamp: bool) -> None:
        result = _clamp_future_value_to_now(value)
        if should_clamp:
            assert result == datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
        else:
            assert result == value


def _manager(resume: KongKonnectResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _page(count: int) -> dict[str, Any]:
    return {"results": [{"request_id": f"r{i}"} for i in range(count)], "meta": {}}


class TestGetRowsPagination:
    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_empty_first_page_yields_nothing(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        mock_fetch.side_effect = [_page(0)]
        batches = list(get_rows("tok", "us", "api_requests", MagicMock(), _manager(), lookback_days=30))
        assert batches == []

    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_saves_state_after_full_page_only(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        mock_fetch.side_effect = [_page(MAX_PAGE_SIZE), _page(2)]
        manager = _manager()

        list(get_rows("tok", "us", "api_requests", MagicMock(), manager, lookback_days=30))

        # One save after the first (full) page; the final short page must NOT persist state.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == MAX_PAGE_SIZE

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    @patch.object(kong_konnect, "make_tracked_session")
    @patch.object(kong_konnect, "_fetch_page")
    def test_resume_reuses_saved_window_not_recomputed(self, mock_fetch: MagicMock, _mock_session: MagicMock) -> None:
        # A crash saved a mid-window checkpoint; resume must re-issue that exact window + offset,
        # never recompute `end` as "now" (which would shift the window and skip/duplicate rows).
        mock_fetch.side_effect = [_page(1)]
        resume = KongKonnectResumeConfig(start="2026-01-01T00:00:00Z", end="2026-01-05T00:00:00Z", offset=5000)

        list(get_rows("tok", "us", "api_requests", MagicMock(), _manager(resume), lookback_days=30))

        body = mock_fetch.call_args_list[0].args[3]
        assert body["time_range"]["start"] == "2026-01-01T00:00:00Z"
        assert body["time_range"]["end"] == "2026-01-05T00:00:00Z"
        assert body["offset"] == 5000


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch.object(kong_konnect, "make_tracked_session")
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status
        mock_session.return_value.post.return_value = response
        assert validate_credentials("tok", "us") is expected

    @patch.object(kong_konnect, "make_tracked_session")
    def test_network_error_is_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.side_effect = requests.ConnectionError()
        assert validate_credentials("tok", "us") is False


class TestKongKonnectSourceResponse:
    def test_source_response_shape(self) -> None:
        response = kong_konnect_source("tok", "eu", "api_requests", MagicMock(), _manager())
        assert response.name == "api_requests"
        assert response.primary_keys == ["request_id"]
        # asc must match the ascending request order for the watermark to advance correctly.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["request_start"]


def _json_response(status: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body or {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    return response


def _control_plane(cp_id: str, cluster_type: str = "CLUSTER_TYPE_CONTROL_PLANE") -> dict[str, Any]:
    return {"id": cp_id, "name": cp_id, "config": {"cluster_type": cluster_type}}


BASE = "https://us.api.konghq.com/v2"


class TestLookupRows:
    @parameterized.expand(
        [
            ("short_page_stops", [[CONTROL_PLANES_PAGE_SIZE, None], [2, None]], 2),
            ("total_reached_stops", [[CONTROL_PLANES_PAGE_SIZE, CONTROL_PLANES_PAGE_SIZE]], 1),
            ("empty_first_page", [[0, 0]], 1),
        ]
    )
    @patch.object(kong_konnect, "make_tracked_session")
    def test_control_planes_page_number_pagination(
        self, _name: str, pages: list[list[int | None]], expected_requests: int, mock_session: MagicMock
    ) -> None:
        responses = []
        for count, total in pages:
            meta = {"page": {"total": total}} if total is not None else {}
            responses.append(
                _json_response(200, {"data": [_control_plane(f"cp{i}") for i in range(count or 0)], "meta": meta})
            )
        mock_session.return_value.get.side_effect = responses

        rows = [row for batch in get_lookup_rows("tok", "us", "control_planes", MagicMock()) for row in batch]

        assert len(rows) == sum(count or 0 for count, _ in pages)
        calls = mock_session.return_value.get.call_args_list
        assert len(calls) == expected_requests
        assert [c.kwargs["params"]["page[number]"] for c in calls] == list(range(1, expected_requests + 1))

    @patch.object(kong_konnect, "make_tracked_session")
    def test_core_entities_fan_out_over_control_planes(self, mock_session: MagicMock) -> None:
        def fake_get(url: str, params: dict[str, Any], timeout: int) -> MagicMock:
            if url == f"{BASE}/control-planes":
                return _json_response(
                    200,
                    {
                        "data": [
                            _control_plane("cp-a"),
                            _control_plane("cp-group", "CLUSTER_TYPE_CONTROL_PLANE_GROUP"),
                            _control_plane("cp-deleted"),
                            _control_plane("cp-b"),
                        ],
                        "meta": {"page": {"total": 4}},
                    },
                )
            if url == f"{BASE}/control-planes/cp-a/core-entities/services":
                if params.get("offset") == "next-token":
                    return _json_response(200, {"data": [{"id": "svc-2"}], "offset": None})
                return _json_response(200, {"data": [{"id": "svc-1"}], "offset": "next-token"})
            if url == f"{BASE}/control-planes/cp-deleted/core-entities/services":
                return _json_response(404)
            if url == f"{BASE}/control-planes/cp-b/core-entities/services":
                # decK can copy entity IDs between control planes, so the same ID shows up again here.
                return _json_response(200, {"data": [{"id": "svc-1"}]})
            raise AssertionError(f"unexpected request to {url}")

        mock_session.return_value.get.side_effect = fake_get

        response = kong_konnect_source("tok", "us", "services", MagicMock(), _manager())
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]

        assert rows == [
            {"id": "svc-1", "control_plane_id": "cp-a"},
            {"id": "svc-2", "control_plane_id": "cp-a"},
            {"id": "svc-1", "control_plane_id": "cp-b"},
        ]
        assert response.primary_keys == ["control_plane_id", "id"]
        mock_session.return_value.post.assert_not_called()

    @patch.object(kong_konnect, "make_tracked_session")
    def test_core_entities_raise_on_auth_error(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _json_response(200, {"data": [_control_plane("cp-a")], "meta": {"page": {"total": 1}}}),
            _json_response(403),
        ]

        with pytest.raises(requests.HTTPError):
            list(get_lookup_rows("tok", "us", "consumers", MagicMock()))


if __name__ == "__main__":
    pytest.main([__file__])
