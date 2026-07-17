import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob import (
    LobResumeConfig,
    LobRetryableError,
    _build_initial_url,
    _fetch_page,
    _format_date_filter_value,
    _parse_date_created,
    get_rows,
    lob_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.settings import LOB_ENDPOINTS


def _make_response(json_body: dict[str, Any] | None = None, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _manager(resume: LobResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestFormatDateFilterValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_date_filter_value(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_date_filter_value(datetime(2026, 3, 4, tzinfo=UTC))


class TestParseDateCreated:
    @parameterized.expand(
        [
            ("z_suffix", "2019-08-08T17:09:14.514Z", datetime(2019, 8, 8, 17, 9, 14, 514000, tzinfo=UTC)),
            ("offset", "2019-08-08T17:09:14+00:00", datetime(2019, 8, 8, 17, 9, 14, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
            ("non_string", 12345, None),
        ]
    )
    def test_parse(self, _name: str, value: object, expected: datetime | None) -> None:
        assert _parse_date_created(value) == expected


class TestBuildInitialUrl:
    def test_incremental_endpoint_forces_ascending_sort(self) -> None:
        url = _build_initial_url(
            LOB_ENDPOINTS["letters"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert url.startswith("https://api.lob.com/v1/letters?")
        assert "sort_by[date_created]=asc" in url
        assert "limit=100" in url
        assert "date_created[gt]" not in url

    def test_incremental_endpoint_with_watermark_adds_filter(self) -> None:
        url = _build_initial_url(
            LOB_ENDPOINTS["postcards"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert "sort_by[date_created]=asc" in url
        assert "date_created[gt]=2026-01-02T03:04:05.000000Z" in url

    def test_full_refresh_endpoint_has_no_sort_or_filter(self) -> None:
        url = _build_initial_url(
            LOB_ENDPOINTS["addresses"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert "sort_by" not in url
        assert "date_created[gt]" not in url
        assert "limit=100" in url


class TestGetRows:
    def test_paginates_following_next_url_and_saves_state_after_each_page(self) -> None:
        pages = [
            {
                "data": [{"id": "ltr_1", "date_created": "2026-01-01T00:00:00Z"}],
                "next_url": "https://api.lob.com/v1/letters?after=cursor1",
            },
            {"data": [{"id": "ltr_2", "date_created": "2026-01-02T00:00:00Z"}], "next_url": None},
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob._fetch_page", side_effect=pages
        ):
            batches = list(get_rows("k", "letters", MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["ltr_1", "ltr_2"]
        # State saved once, after yielding the first page (which had a next_url); not after the last.
        manager.save_state.assert_called_once_with(
            LobResumeConfig(next_url="https://api.lob.com/v1/letters?after=cursor1")
        )

    def test_stops_on_empty_data(self) -> None:
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob._fetch_page",
            side_effect=[{"data": []}],
        ):
            batches = list(get_rows("k", "letters", MagicMock(), manager))
        assert batches == []
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_next_url(self) -> None:
        manager = _manager(LobResumeConfig(next_url="https://api.lob.com/v1/letters?after=saved"))
        captured: list[str] = []

        def _fetch(_session, url, *_args, **_kwargs):
            captured.append(url)
            return {"data": [{"id": "ltr_9", "date_created": "2026-01-09T00:00:00Z"}], "next_url": None}

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob._fetch_page", side_effect=_fetch
        ):
            list(get_rows("k", "letters", MagicMock(), manager))

        assert captured == ["https://api.lob.com/v1/letters?after=saved"]

    def test_incremental_watermark_guard_stops_when_page_predates_watermark(self) -> None:
        # Defends against the cursor dropping the time filter on later pages: every row here predates
        # the watermark, and there is still a next_url, so pagination must stop instead of walking back.
        pages = [
            {
                "data": [{"id": "ltr_old", "date_created": "2020-01-01T00:00:00Z"}],
                "next_url": "https://api.lob.com/v1/letters?after=cursor",
            },
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob._fetch_page", side_effect=pages
        ):
            batches = list(
                get_rows(
                    "k",
                    "letters",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )

        # The page is still yielded (merge dedupes), but we stop before following the next_url.
        assert [item["id"] for batch in batches for item in batch] == ["ltr_old"]
        manager.save_state.assert_not_called()

    def test_full_refresh_endpoint_ignores_watermark_guard(self) -> None:
        # Full-refresh endpoints have no incremental support, so the watermark guard never engages
        # even if a stale last-value is passed in.
        pages = [
            {
                "data": [{"id": "adr_1", "date_created": "2020-01-01T00:00:00Z"}],
                "next_url": "https://api.lob.com/v1/addresses?after=c",
            },
            {"data": [{"id": "adr_2", "date_created": "2019-01-01T00:00:00Z"}], "next_url": None},
        ]
        manager = _manager()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob._fetch_page", side_effect=pages
        ):
            batches = list(
                get_rows(
                    "k",
                    "addresses",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        assert [item["id"] for batch in batches for item in batch] == ["adr_1", "adr_2"]


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({}, status=status)
        # Call the undecorated function so a single attempt raises immediately instead of
        # exercising tenacity's exponential backoff.
        with pytest.raises(LobRetryableError):
            _fetch_page.__wrapped__(session, "https://api.lob.com/v1/letters", "k", {}, MagicMock())  # type: ignore[attr-defined]

    def test_client_error_raises_for_status(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({"error": {"message": "bad"}}, status=401)
        with pytest.raises(Exception):
            _fetch_page(session, "https://api.lob.com/v1/letters", "k", {}, MagicMock())

    def test_uses_http_basic_auth_with_blank_password(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({"data": []})
        _fetch_page(session, "https://api.lob.com/v1/letters", "my_key", {}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["auth"] == ("my_key", "")


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({}, status=status)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob.make_tracked_session",
            return_value=session,
        ):
            is_valid, status_code = validate_credentials("k")
        assert is_valid is expected_valid
        assert status_code == status

    def test_network_error_returns_false_and_none_status(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob.make_tracked_session",
            return_value=session,
        ):
            is_valid, status_code = validate_credentials("k")
        assert is_valid is False
        assert status_code is None


class TestLobSource:
    @parameterized.expand([("letters", "asc"), ("postcards", "asc"), ("addresses", "desc"), ("campaigns", "desc")])
    def test_sort_mode_matches_incremental_support(self, endpoint: str, expected_sort: str) -> None:
        response = lob_source("k", endpoint, MagicMock(), _manager())
        assert response.sort_mode == expected_sort
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["date_created"]
        assert response.partition_mode == "datetime"
