from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft import (
    SALESLOFT_BASE_URL,
    SalesloftResumeConfig,
    _build_params,
    _build_url,
    _format_datetime,
    get_rows,
    salesloft_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import SALESLOFT_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int, body: Any = None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(self._body)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error: for url", response=self)  # type: ignore[arg-type]


def _page(items: list[dict], next_page: int | None) -> dict:
    return {"data": items, "metadata": {"paging": {"per_page": 100, "next_page": next_page}}}


def _session_returning(responses: list[_FakeResponse]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


def _manager(can_resume: bool = False, state: SalesloftResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_full_refresh_endpoint_only_sets_page_size(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["groups"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100}

    def test_incremental_endpoint_sets_ascending_sort_without_value(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params == {"per_page": 100, "sort_direction": "ASC"}

    def test_incremental_endpoint_sets_updated_at_filter(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["sort_direction"] == "ASC"
        assert params["updated_at[gte]"] == "2026-03-04T02:58:14.000Z"

    def test_incremental_field_value_ignored_when_flag_off(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "updated_at[gte]" not in params

    def test_falls_back_to_updated_at_when_field_missing(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["accounts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=None,
        )
        assert "updated_at[gte]" in params


class TestBuildUrl:
    def test_encodes_bracketed_filter_params(self) -> None:
        url = _build_url(
            f"{SALESLOFT_BASE_URL}/people",
            {"per_page": 100, "page": 1, "updated_at[gte]": "2026-03-04T02:58:14.000Z"},
        )
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert parsed.path == "/v2/people"
        assert qs["per_page"] == ["100"]
        assert qs["updated_at[gte]"] == ["2026-03-04T02:58:14.000Z"]


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session_factory, status_code, expected) -> None:
        mock_session_factory.return_value = _session_returning([_FakeResponse(status_code)])

        assert validate_credentials("sl_token") is expected

        call = mock_session_factory.return_value.get.call_args
        assert call.args[0] == f"{SALESLOFT_BASE_URL}/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sl_token"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_validate_credentials_swallows_transport_errors(self, mock_session_factory) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        mock_session_factory.return_value = session

        assert validate_credentials("sl_token") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_paginates_until_next_page_is_null(self, mock_session_factory) -> None:
        responses = [
            _FakeResponse(200, _page([{"id": 1}, {"id": 2}], next_page=2)),
            _FakeResponse(200, _page([{"id": 3}], next_page=None)),
        ]
        mock_session_factory.return_value = _session_returning(responses)
        manager = _manager()

        batches = list(get_rows("sl_token", "people", mock.MagicMock(), manager, should_use_incremental_field=False))

        assert [row["id"] for batch in batches for row in batch] == [1, 2, 3]
        assert mock_session_factory.return_value.get.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_saves_resume_state_after_yielding_each_page(self, mock_session_factory) -> None:
        responses = [
            _FakeResponse(200, _page([{"id": 1}], next_page=2)),
            _FakeResponse(200, _page([{"id": 2}], next_page=None)),
        ]
        mock_session_factory.return_value = _session_returning(responses)
        manager = _manager()

        list(get_rows("sl_token", "people", mock.MagicMock(), manager, should_use_incremental_field=False))

        # State saved once: after page 1, pointing at page 2. No save after the final page.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, SalesloftResumeConfig)
        assert parse_qs(urlparse(saved.next_url).query)["page"] == ["2"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_resumes_from_saved_url(self, mock_session_factory) -> None:
        resume_url = f"{SALESLOFT_BASE_URL}/people?per_page=100&page=5"
        mock_session_factory.return_value = _session_returning([_FakeResponse(200, _page([{"id": 9}], next_page=None))])
        manager = _manager(can_resume=True, state=SalesloftResumeConfig(next_url=resume_url))

        batches = list(get_rows("sl_token", "people", mock.MagicMock(), manager, should_use_incremental_field=False))

        assert [row["id"] for batch in batches for row in batch] == [9]
        assert mock_session_factory.return_value.get.call_args.args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_empty_page_yields_nothing(self, mock_session_factory) -> None:
        mock_session_factory.return_value = _session_returning([_FakeResponse(200, _page([], next_page=None))])

        batches = list(get_rows("sl_token", "people", mock.MagicMock(), _manager(), should_use_incremental_field=False))

        assert batches == []

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_retries_on_retryable_status_then_succeeds(self, mock_session_factory, _mock_sleep) -> None:
        responses = [
            _FakeResponse(429),
            _FakeResponse(503),
            _FakeResponse(200, _page([{"id": 1}], next_page=None)),
        ]
        mock_session_factory.return_value = _session_returning(responses)

        batches = list(get_rows("sl_token", "people", mock.MagicMock(), _manager(), should_use_incremental_field=False))

        assert [row["id"] for batch in batches for row in batch] == [1]
        assert mock_session_factory.return_value.get.call_count == 3

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
    )
    def test_non_retryable_status_raises(self, mock_session_factory) -> None:
        mock_session_factory.return_value = _session_returning([_FakeResponse(404)])

        with pytest.raises(requests.HTTPError):
            list(get_rows("sl_token", "people", mock.MagicMock(), _manager(), should_use_incremental_field=False))


class TestSalesloftSource:
    @pytest.mark.parametrize("endpoint", sorted(SALESLOFT_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = salesloft_source("sl_token", endpoint, mock.MagicMock(), _manager())

        config = SALESLOFT_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_key_is_always_created_at_never_updated_at(self) -> None:
        for config in SALESLOFT_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")
