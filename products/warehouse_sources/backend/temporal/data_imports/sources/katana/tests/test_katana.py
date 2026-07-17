from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.katana import katana
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana import (
    KatanaRateLimitError,
    KatanaResumeConfig,
    KatanaRetryableError,
    _build_base_params,
    _clamp_future_value_to_now,
    _format_incremental_value,
    _request_page,
    _wait_katana,
    get_rows,
    katana_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import KATANA_ENDPOINTS

# A stand-in API key long enough to be caught by the transport's value-based redaction.
_SECRET_KEY = "katana-secret-key-abcdef123456"


def _fake_response(status_code: int = 200, body: Any = None, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.headers = headers or {}
    response.json.return_value = body if body is not None else {}
    response.text = "" if body is None else str(body)
    return response


def _fake_manager(resume: KatanaResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_plus_offset(self) -> None:
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestClampFutureValue:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_clamped_to_now(self) -> None:
        clamped = _clamp_future_value_to_now(datetime(2027, 1, 1, tzinfo=UTC))
        assert clamped == datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_untouched(self) -> None:
        past = datetime(2026, 1, 1, tzinfo=UTC)
        assert _clamp_future_value_to_now(past) == past


class TestBuildBaseParams:
    def test_incremental_filter_uses_min_suffix(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == {"updated_at_min": "2026-03-04T02:58:14.000Z"}

    def test_respects_user_chosen_incremental_field(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert "created_at_min" in params
        assert "updated_at_min" not in params

    def test_falls_back_to_default_incremental_field(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["inventory_movements"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=None,
        )
        assert "created_at_min" in params

    def test_first_sync_has_no_filter(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params == {}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["inventory"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == {}

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_clamped(self) -> None:
        params = _build_base_params(
            KATANA_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == {"updated_at_min": "2026-06-15T12:00:00.000Z"}


class TestRequestPage:
    def test_429_raises_rate_limit_with_retry_after(self) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(429, headers={"Retry-After": "12"})
        with pytest.raises(KatanaRateLimitError) as exc:
            _request_page(session, "url", {}, {}, MagicMock(), MagicMock())
        assert exc.value.retry_after == 12.0

    def test_5xx_raises_retryable(self) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(503)
        with pytest.raises(KatanaRetryableError):
            _request_page(session, "url", {}, {}, MagicMock(), MagicMock())

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_4xx_raises_matchable_http_error_without_leaking_key(self, _name: str, status: int, reason: str) -> None:
        # A credential-bearing final URL (redirect echoing the key) must never reach the exception text,
        # but the stable `<status> Client Error: <reason> for url: https://api.katanamrp.com...` prefix
        # that `KatanaSource.get_non_retryable_errors()` matches on must survive scrubbing.
        response = _fake_response(status)
        response.reason = reason
        response.url = f"https://api.katanamrp.com/v1/customers?token={_SECRET_KEY}"
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError) as exc:
            _request_page(session, "https://api.katanamrp.com/v1/customers", {}, {}, MagicMock(), MagicMock())
        message = str(exc.value)
        assert _SECRET_KEY not in message
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.katanamrp.com/v1/customers")

    def test_200_returns_body(self) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"data": [{"id": 1}]})
        result = _request_page(session, "url", {}, {}, MagicMock(), MagicMock())
        assert result == {"data": [{"id": 1}]}

    def test_empty_data_list_is_accepted(self) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"data": []})
        assert _request_page(session, "url", {}, {}, MagicMock(), MagicMock()) == {"data": []}

    @parameterized.expand([("missing_data_key", {"items": []}), ("not_a_dict", [1, 2, 3])])
    def test_malformed_envelope_is_retryable(self, _name: str, body: Any) -> None:
        # A 2xx body without a `data` key must fail loudly (retryable), not silently end the sync.
        session = MagicMock()
        session.get.return_value = _fake_response(200, body)
        with pytest.raises(KatanaRetryableError):
            _request_page(session, "url", {}, {}, MagicMock(), MagicMock())


class TestWaitKatana:
    def test_honours_retry_after(self) -> None:
        state = MagicMock()
        state.outcome.exception.return_value = KatanaRateLimitError(retry_after=7.0)
        assert _wait_katana(state) == 7.0

    def test_backoff_when_no_retry_after(self) -> None:
        state = MagicMock()
        state.outcome.exception.return_value = KatanaRetryableError("boom")
        state.attempt_number = 3
        assert _wait_katana(state) == 8.0


class TestGetRows:
    @patch.object(katana.time, "sleep", lambda *_: None)
    @patch.object(katana, "make_tracked_session")
    def test_paginates_until_short_page(self, mock_session_factory: MagicMock) -> None:
        # Two full pages then a short page terminates pagination.
        full_page = {"data": [{"id": i} for i in range(katana.PAGE_SIZE)]}
        short_page = {"data": [{"id": 9001}]}
        session = MagicMock()
        session.get.side_effect = [
            _fake_response(200, full_page),
            _fake_response(200, full_page),
            _fake_response(200, short_page),
        ]
        mock_session_factory.return_value = session

        tables = list(
            get_rows(api_key="k", endpoint="customers", logger=MagicMock(), resumable_source_manager=_fake_manager())
        )
        rows = [row for table in tables for row in table.to_pylist()]
        assert len(rows) == 2 * katana.PAGE_SIZE + 1
        assert session.get.call_count == 3
        # The key must be registered with the tracked transport so it's masked in logged URLs / samples.
        mock_session_factory.assert_called_once_with(redact_values=("k",))

    @patch.object(katana.time, "sleep", lambda *_: None)
    @patch.object(katana, "make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"data": []})
        mock_session_factory.return_value = session

        tables = list(
            get_rows(api_key="k", endpoint="customers", logger=MagicMock(), resumable_source_manager=_fake_manager())
        )
        assert tables == []
        assert session.get.call_count == 1

    @patch.object(katana.time, "sleep", lambda *_: None)
    @patch.object(katana, "make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200, {"data": [{"id": 1}]})
        mock_session_factory.return_value = session

        list(
            get_rows(
                api_key="k",
                endpoint="customers",
                logger=MagicMock(),
                resumable_source_manager=_fake_manager(KatanaResumeConfig(page=4)),
            )
        )
        # The first (and only) request must start at the resumed page, not page 1.
        _, kwargs = session.get.call_args_list[0]
        assert kwargs["params"]["page"] == 4

    @patch.object(katana.time, "sleep", lambda *_: None)
    @patch.object(katana, "make_tracked_session")
    def test_incremental_filter_sent_on_every_page(self, mock_session_factory: MagicMock) -> None:
        full_page = {"data": [{"id": i} for i in range(katana.PAGE_SIZE)]}
        session = MagicMock()
        session.get.side_effect = [_fake_response(200, full_page), _fake_response(200, {"data": []})]
        mock_session_factory.return_value = session

        list(
            get_rows(
                api_key="k",
                endpoint="customers",
                logger=MagicMock(),
                resumable_source_manager=_fake_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )
        for call in session.get.call_args_list:
            assert call.kwargs["params"]["updated_at_min"] == "2026-01-01T00:00:00.000Z"


class TestKatanaSource:
    @parameterized.expand(
        [
            ("customers", ["id"], "created_at"),
            ("inventory", ["variant_id", "location_id"], None),
            ("price_lists", ["id"], None),
            ("inventory_movements", ["id"], "created_at"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str], partition_key: str | None) -> None:
        response = katana_source(
            api_key="k", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "desc"
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @patch.object(katana, "make_tracked_session")
    def test_valid_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(200)
        mock_session_factory.return_value = session
        assert katana.validate_credentials("good-key") is True
        # The key must be registered with the tracked transport so it's masked in logged URLs / samples.
        mock_session_factory.assert_called_once_with(redact_values=("good-key",))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @patch.object(katana, "make_tracked_session")
    def test_invalid_key(self, _name: str, status: int, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = _fake_response(status)
        mock_session_factory.return_value = session
        assert katana.validate_credentials("bad-key") is False

    @patch.object(katana, "make_tracked_session")
    def test_network_error_is_false(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("no network")
        mock_session_factory.return_value = session
        assert katana.validate_credentials("key") is False
