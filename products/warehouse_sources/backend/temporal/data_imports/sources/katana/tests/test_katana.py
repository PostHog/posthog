import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana import (
    PAGE_SIZE,
    KatanaResumeConfig,
    _clamp_future_value_to_now,
    _format_incremental_value,
    katana_source,
    validate_credentials,
)

# A stand-in API key long enough to be caught by the transport's value-based redaction.
_SECRET_KEY = "katana-secret-key-abcdef123456"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the katana module.
KATANA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None = None,
    *,
    status: int = 200,
    drop_data: bool = False,
    body: Any = None,
    url: str = "https://api.katanamrp.com/v1/customers",
    reason: str = "OK",
    headers: dict[str, str] | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = reason
    if headers:
        resp.headers.update(headers)
    if body is not None:
        payload: Any = body
    elif drop_data:
        payload = {"items": items or []}
    else:
        payload = {"data": items if items is not None else []}
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume: KatanaResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(session_factory: MagicMock, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {"api_key": "k", "endpoint": "customers", "team_id": 1, "job_id": "j"}
    defaults.update(kwargs)
    defaults.setdefault("resumable_source_manager", _make_manager())
    return katana_source(**defaults)


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


class TestPagination:
    @patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession: MagicMock) -> None:
        # Two full pages then a short (non-empty) page terminates pagination WITHOUT an extra request —
        # Katana has no next-page cursor, so a page below PAGE_SIZE is the last one.
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        short_page = [{"id": 9001}]
        params = _wire(session, [_response(full_page), _response(full_page), _response(short_page)])

        rows = _rows(_source(MockSession))

        assert len(rows) == 2 * PAGE_SIZE + 1
        assert session.send.call_count == 3
        assert [p["page"] for p in params] == [1, 2, 3]
        assert all(p["limit"] == PAGE_SIZE for p in params)

    @patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()

        rows = _rows(_source(MockSession, resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_saved_after_full_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page), _response([{"id": 1}])])
        manager = _make_manager()

        _rows(_source(MockSession, resumable_source_manager=manager))

        # Checkpoint saved after the first full page (points at the next page); the short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == KatanaResumeConfig(page=2)

    @patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(_source(MockSession, resumable_source_manager=_make_manager(KatanaResumeConfig(page=4))))

        # The first (and only) request must start at the resumed page, not page 1.
        assert params[0]["page"] == 4


class TestIncrementalFilter:
    @patch(CLIENT_SESSION_PATCH)
    def test_filter_sent_on_every_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([])])

        _rows(
            _source(
                MockSession,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert len(params) == 2
        for p in params:
            assert p["updated_at_min"] == "2026-01-01T00:00:00.000Z"

    @patch(CLIENT_SESSION_PATCH)
    def test_respects_user_chosen_incremental_field(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                MockSession,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_at_min" in params[0]
        assert "updated_at_min" not in params[0]

    @patch(CLIENT_SESSION_PATCH)
    def test_falls_back_to_default_incremental_field(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                MockSession,
                endpoint="inventory_movements",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field=None,
            )
        )

        assert "created_at_min" in params[0]

    @patch(CLIENT_SESSION_PATCH)
    def test_first_sync_has_no_filter(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                MockSession,
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="updated_at",
            )
        )

        assert "updated_at_min" not in params[0]

    @patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"variant_id": 1, "location_id": 2}])])

        _rows(
            _source(
                MockSession,
                endpoint="inventory",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert params[0] == {"page": 1, "limit": PAGE_SIZE}

    @freeze_time("2026-06-15T12:00:00Z")
    @patch(CLIENT_SESSION_PATCH)
    def test_future_cursor_clamped(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                MockSession,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert params[0]["updated_at_min"] == "2026-06-15T12:00:00.000Z"


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @patch(CLIENT_SESSION_PATCH)
    def test_4xx_raises_matchable_http_error_without_leaking_key(
        self, _name: str, status: int, reason: str, MockSession: MagicMock
    ) -> None:
        # A credential-bearing final URL (a redirect echoing the key into the URL) must never reach the
        # exception text, but the stable `<status> Client Error: <reason> for url: https://api.katanamrp.com...`
        # prefix that KatanaSource.get_non_retryable_errors() matches on must survive redaction.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    status=status,
                    reason=reason,
                    url=f"https://api.katanamrp.com/v1/customers?token={_SECRET_KEY}",
                )
            ],
        )

        with pytest.raises(HTTPError) as exc:
            _rows(_source(MockSession, api_key=_SECRET_KEY))

        message = str(exc.value)
        assert _SECRET_KEY not in message
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.katanamrp.com/v1/customers")

    @parameterized.expand([("missing_data_key", {"items": []}), ("not_a_dict", [1, 2, 3])])
    @patch("time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_malformed_2xx_envelope_is_retried(
        self, _name: str, body: Any, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        # A 200 body without a list `data` key must NOT silently end the sync as an empty page — it's
        # reissued (retryable), then the valid page is read.
        session = MockSession.return_value
        _wire(session, [_response(body=body), _response([{"id": 7}])])

        rows = _rows(_source(MockSession))

        assert [r["id"] for r in rows] == [7]
        assert session.send.call_count == 2

    @parameterized.expand([("server_error", 503), ("rate_limited", 429)])
    @patch("time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_transient_status_is_retried(
        self, _name: str, status: int, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        session = MockSession.return_value
        headers = {"Retry-After": "1"} if status == 429 else None
        _wire(session, [_response(status=status, reason="err", headers=headers), _response([{"id": 5}])])

        rows = _rows(_source(MockSession))

        assert [r["id"] for r in rows] == [5]
        assert session.send.call_count == 2


class TestKatanaSourceResponse:
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
            api_key="k", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
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
    @patch(KATANA_SESSION_PATCH)
    def test_valid_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        mock_session_factory.return_value = session

        assert validate_credentials("good-key") is True
        # The key must be registered with the tracked transport so it's masked in logged URLs / samples.
        mock_session_factory.assert_called_once_with(redact_values=("good-key",))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @patch(KATANA_SESSION_PATCH)
    def test_invalid_key(self, _name: str, status: int, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        mock_session_factory.return_value = session

        assert validate_credentials("bad-key") is False

    @patch(KATANA_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("no network")
        mock_session_factory.return_value = session

        assert validate_credentials("key") is False
