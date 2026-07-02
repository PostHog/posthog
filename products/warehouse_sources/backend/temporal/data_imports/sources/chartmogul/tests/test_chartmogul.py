from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul import (
    ChartMogulResumeConfig,
    _build_initial_params,
    _format_start_date,
    chartmogul_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import CHARTMOGUL_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError(f"HTTP {self.status_code}")


def _fake_session(responses: list[_FakeResponse]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


def _manager(can_resume: bool = False, resume_state: ChartMogulResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_format_start_date(self, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected

    def test_no_tz_offset_in_output(self) -> None:
        assert "+00:00" not in _format_start_date(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildInitialParams:
    def test_paginated_endpoint_sets_per_page(self) -> None:
        params = _build_initial_params(CHARTMOGUL_ENDPOINTS["customers"], False, None)
        assert params["per_page"] == 200
        assert "start-date" not in params

    def test_non_paginated_endpoint_omits_per_page(self) -> None:
        params = _build_initial_params(CHARTMOGUL_ENDPOINTS["data_sources"], False, None)
        assert "per_page" not in params

    def test_activities_incremental_sets_start_date(self) -> None:
        params = _build_initial_params(
            CHARTMOGUL_ENDPOINTS["activities"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert params["start-date"] == "2026-01-01T00:00:00"

    def test_no_start_date_when_incremental_disabled(self) -> None:
        params = _build_initial_params(
            CHARTMOGUL_ENDPOINTS["activities"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert "start-date" not in params

    def test_non_incremental_endpoint_never_sets_start_date(self) -> None:
        params = _build_initial_params(
            CHARTMOGUL_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert "start-date" not in params


class TestGetRows:
    def test_paginates_across_cursors(self) -> None:
        responses = [
            _FakeResponse(200, {"entries": [{"uuid": "a"}], "has_more": True, "cursor": "c1"}),
            _FakeResponse(200, {"entries": [{"uuid": "b"}], "has_more": False, "cursor": None}),
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=_fake_session(responses),
        ):
            batches = list(get_rows("key", "customers", MagicMock(), manager))

        assert batches == [[{"uuid": "a"}], [{"uuid": "b"}]]

    def test_saves_state_after_each_page(self) -> None:
        responses = [
            _FakeResponse(200, {"entries": [{"uuid": "a"}], "has_more": True, "cursor": "c1"}),
            _FakeResponse(200, {"entries": [{"uuid": "b"}], "has_more": False, "cursor": None}),
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=_fake_session(responses),
        ):
            list(get_rows("key", "customers", MagicMock(), manager))

        manager.save_state.assert_called_once_with(ChartMogulResumeConfig(cursor="c1"))

    def test_resumes_from_saved_cursor(self) -> None:
        session = _fake_session([_FakeResponse(200, {"entries": [{"uuid": "b"}], "has_more": False, "cursor": None})])
        manager = _manager(can_resume=True, resume_state=ChartMogulResumeConfig(cursor="resume-cursor"))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=session,
        ):
            list(get_rows("key", "customers", MagicMock(), manager))

        called_url = session.get.call_args_list[0].args[0]
        assert "cursor=resume-cursor" in called_url

    def test_non_paginated_endpoint_fetches_once(self) -> None:
        session = _fake_session(
            [_FakeResponse(200, {"data_sources": [{"uuid": "ds1"}], "has_more": True, "cursor": "ignored"})]
        )
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=session,
        ):
            batches = list(get_rows("key", "data_sources", MagicMock(), manager))

        assert batches == [[{"uuid": "ds1"}]]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_empty_page_is_not_yielded(self) -> None:
        session = _fake_session([_FakeResponse(200, {"plans": [], "has_more": False, "cursor": None})])
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=session,
        ):
            batches = list(get_rows("key", "plans", MagicMock(), manager))

        assert batches == []

    @pytest.mark.parametrize("status", [429, 503])
    @patch("tenacity.nap.time.sleep", return_value=None)
    def test_retryable_status_codes_recover(self, _mock_sleep: MagicMock, status: int) -> None:
        # A single retryable response then success: the tenacity retry should
        # recover and still yield the data. tenacity's backoff sleep is patched
        # out to keep the test fast and deterministic.
        responses = [
            _FakeResponse(status, {}),
            _FakeResponse(200, {"plans": [{"uuid": "p1"}], "has_more": False, "cursor": None}),
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=_fake_session(responses),
        ):
            batches = list(get_rows("key", "plans", MagicMock(), manager))

        assert batches == [[{"uuid": "p1"}]]


class TestValidateCredentials:
    @pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False)])
    def test_status_mapping(self, status: int, expected: bool) -> None:
        session = _fake_session([_FakeResponse(status, {})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=session,
        ):
            assert validate_credentials("key") is expected

    def test_exception_returns_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul._get_session",
            return_value=session,
        ):
            assert validate_credentials("key") is False


class TestChartmogulSource:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("customers", ["uuid"], None),
            ("plans", ["uuid"], None),
            ("plan_groups", ["uuid"], None),
            ("invoices", ["uuid"], "date"),
            ("activities", ["uuid"], "date"),
            ("data_sources", ["uuid"], "created_at"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = chartmogul_source("key", endpoint, MagicMock(), _manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
