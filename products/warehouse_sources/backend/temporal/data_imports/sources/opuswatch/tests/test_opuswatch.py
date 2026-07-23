import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch import (
    OPUSWatchResumeConfig,
    build_date_window_params,
    opuswatch_source,
)

TODAY = date(2025, 1, 10)


class TestBuildDateWindowParams:
    @pytest.mark.parametrize(
        ("start_date", "should_use_incremental_field", "last_value", "expected"),
        [
            # Full refresh: CREATED window from the configured start date up to today.
            ("20250101", False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # Blank start date falls back to the default.
            (None, False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            ("  ", False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # First incremental run has no watermark yet -> CREATED window.
            ("20250101", True, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # Incremental with a watermark: UPDATED window covering watermark day -> today.
            ("20250101", True, datetime(2025, 1, 8, 15, 30), {"filter_date_by": "UPDATED", "days_till_date": "3"}),
            ("20250101", True, "2025-01-08T15:30:00Z", {"filter_date_by": "UPDATED", "days_till_date": "3"}),
            # Watermark on today's date still requests at least one day.
            ("20250101", True, datetime(2025, 1, 10, 1, 0), {"filter_date_by": "UPDATED", "days_till_date": "1"}),
            # An unparseable watermark falls back to the CREATED window rather than failing.
            ("20250101", True, "not-a-date", {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
        ],
    )
    def test_window_params(
        self,
        start_date: Optional[str],
        should_use_incremental_field: bool,
        last_value: Any,
        expected: dict[str, str],
    ):
        params = build_date_window_params(start_date, should_use_incremental_field, last_value, today=TODAY)

        for key in ("return_breaks", "return_leaves", "return_archived"):
            assert params.pop(key) == "true"
        assert params == expected


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _fresh_manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestOPUSWatchSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        sent_headers: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_prepare(request: Any) -> Any:
            # Apply the auth callable like a real session would, so the test observes
            # the header the API key is injected under.
            if request.auth is not None:
                request.auth(request)
            return request

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            sent_headers.append(dict(request.headers or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = fake_prepare
            mock_session.send.side_effect = fake_send

            resource = opuswatch_source(
                api_key="test-key",
                start_date="20250101",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            for page in cast(Iterable[list[dict[str, Any]]], resource):
                rows.extend(page)

        return rows, sent_params, sent_headers

    def test_master_endpoint_fetches_single_root_list_page(self):
        manager = _fresh_manager()
        responses = [_make_http_response([{"id": "w1"}, {"id": "w2"}])]

        rows, sent_params, sent_headers = self._drive("workers", manager, responses)

        assert rows == [{"id": "w1"}, {"id": "w2"}]
        assert len(sent_params) == 1
        # Master endpoints take no pagination or date-window params.
        assert sent_params[0] == {}
        assert sent_headers[0]["key"] == "test-key"
        manager.load_state.assert_not_called()
        manager.save_state.assert_not_called()

    def test_client_endpoint_wraps_single_object_as_one_row(self):
        manager = _fresh_manager()
        responses = [_make_http_response({"name": "Acme Nursery", "updatedTimestamp": "2025-01-05T00:00:00Z"})]

        rows, _, _ = self._drive("client", manager, responses)

        assert rows == [{"name": "Acme Nursery", "updatedTimestamp": "2025-01-05T00:00:00Z"}]

    @pytest.mark.parametrize("endpoint", ["registrations", "sessions"])
    def test_transactional_pagination_advances_offset_and_checkpoints(self, endpoint: str):
        manager = _fresh_manager()

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch.PAGE_SIZE", 2):
            responses = [
                _make_http_response({"data": [{"id": "1"}, {"id": "2"}]}),
                _make_http_response({"data": [{"id": "3"}, {"id": "4"}]}),
                _make_http_response({"data": [{"id": "5"}]}),
            ]
            rows, sent_params, _ = self._drive(endpoint, manager, responses)

        assert [row["id"] for row in rows] == ["1", "2", "3", "4", "5"]
        assert [p.get("offset") for p in sent_params] == [0, 2, 4]
        assert [p.get("limit") for p in sent_params] == [2, 2, 2]
        # Full refresh requests the CREATED window from the start date on every page.
        assert all(p["filter_date_by"] == "CREATED" for p in sent_params)
        assert all(p["date"] == "20250101" for p in sent_params)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [OPUSWatchResumeConfig(offset=2), OPUSWatchResumeConfig(offset=4)]

    def test_incremental_run_requests_updated_window(self):
        manager = _fresh_manager()
        responses = [_make_http_response({"data": [{"id": "1", "updatedTimestamp": "2025-01-09T10:00:00Z"}]})]

        _, sent_params, _ = self._drive(
            "registrations",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 8, 12, 0),
        )

        assert sent_params[0]["filter_date_by"] == "UPDATED"
        assert "days_till_date" in sent_params[0]
        assert "date" not in sent_params[0]

    def test_resume_seeds_paginator_with_saved_offset(self):
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = OPUSWatchResumeConfig(offset=4)

        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch.PAGE_SIZE", 2):
            responses = [_make_http_response({"data": [{"id": "5"}]})]
            _, sent_params, _ = self._drive("registrations", manager, responses)

        assert [p.get("offset") for p in sent_params] == [4]
        manager.load_state.assert_called_once()
        manager.save_state.assert_not_called()
