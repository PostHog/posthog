import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import (
    DEFAULT_PAGE_SIZE,
    MetorialResumeConfig,
    _format_incremental_value,
    metorial_source,
    validate_credentials,
)

# A stand-in API key long enough to be caught by the transport's value-based redaction.
_SECRET_KEY = "metorial_sk_abcdef1234567890"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the metorial module.
METORIAL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None = None,
    *,
    has_more_after: bool = False,
    status: int = 200,
    body: Any = None,
    url: str = "https://api.metorial.com/tool-calls",
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
    else:
        payload = {"items": items if items is not None else [], "pagination": {"has_more_after": has_more_after}}
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume: MetorialResumeConfig | None = None) -> MagicMock:
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
    defaults: dict[str, Any] = {"api_key": "metorial_sk_x", "endpoint": "tool_calls", "team_id": 1, "job_id": "j"}
    defaults.update(kwargs)
    defaults.setdefault("resumable_source_manager", _make_manager())
    return metorial_source(**defaults)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "ses_cursor", "ses_cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        # The server filter rejects a +00:00 offset; the watermark must serialize with a Z suffix.
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestPagination:
    @patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_has_more_after_false(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "tcl_1"}, {"id": "tcl_2"}], has_more_after=True),
                _response([{"id": "tcl_3"}], has_more_after=False),
            ],
        )

        rows = _rows(_source(MockSession))

        assert [r["id"] for r in rows] == ["tcl_1", "tcl_2", "tcl_3"]
        # No extra empty request: has_more_after=False on page two ends the sync.
        assert session.send.call_count == 2
        # Page one carries no cursor; page two pages from the last id of page one.
        assert "after" not in params[0]
        assert params[1]["after"] == "tcl_2"
        assert all(p["order"] == "asc" and p["limit"] == DEFAULT_PAGE_SIZE for p in params)

    @patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more_after=False)])
        manager = _make_manager()

        rows = _rows(_source(MockSession, resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @patch(CLIENT_SESSION_PATCH)
    def test_drops_sensitive_fields_on_sessions(self, MockSession: MagicMock) -> None:
        # A live client_secret must never be persisted to the warehouse.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "ses_1", "client_secret": "metorial_fk_x"}], has_more_after=False)])

        rows = _rows(_source(MockSession, endpoint="sessions"))

        assert rows == [{"id": "ses_1"}]


class TestResume:
    @patch(CLIENT_SESSION_PATCH)
    def test_saves_next_cursor_after_each_page(self, MockSession: MagicMock) -> None:
        # Saving after (not before) yielding means a crash re-fetches the page rather than skipping it.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "prn_1"}], has_more_after=True),
                _response([{"id": "prn_2"}], has_more_after=False),
            ],
        )
        manager = _make_manager()

        _rows(_source(MockSession, endpoint="provider_runs", resumable_source_manager=manager))

        # Only the page that had a successor persists a cursor; the terminal page does not.
        saved = [call.args[0].after for call in manager.save_state.call_args_list]
        assert saved == ["prn_1"]

    @patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: MagicMock) -> None:
        # A resumed run must continue from the persisted cursor, not restart the whole stream.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "prn_9"}], has_more_after=False)])

        rows = _rows(
            _source(
                MockSession,
                endpoint="provider_runs",
                resumable_source_manager=_make_manager(MetorialResumeConfig(after="prn_8")),
            )
        )

        assert params[0]["after"] == "prn_8"
        assert [r["id"] for r in rows] == ["prn_9"]


class TestIncrementalFilter:
    @patch(CLIENT_SESSION_PATCH)
    def test_builds_gt_filter_for_chosen_field_on_every_page(self, MockSession: MagicMock) -> None:
        # Dropping or misnaming this filter turns every "incremental" sync into a full refresh.
        session = MockSession.return_value
        params = _wire(
            session,
            [_response([{"id": "ses_1"}], has_more_after=True), _response([{"id": "ses_2"}], has_more_after=False)],
        )

        _rows(
            _source(
                MockSession,
                endpoint="sessions",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert len(params) == 2
        for p in params:
            assert p["updated_at[gt]"] == "2026-03-04T02:58:14.000Z"

    @patch(CLIENT_SESSION_PATCH)
    def test_honors_user_incremental_field_over_default(self, MockSession: MagicMock) -> None:
        # sessions default is updated_at; the user picking created_at must be respected.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "ses_1"}], has_more_after=False)])

        _rows(
            _source(
                MockSession,
                endpoint="sessions",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_at[gt]" in params[0]
        assert "updated_at[gt]" not in params[0]

    @patch(CLIENT_SESSION_PATCH)
    def test_first_sync_has_no_filter(self, MockSession: MagicMock) -> None:
        # No watermark yet: sending an empty gt filter would 400 (or silently sync nothing).
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "ses_1"}], has_more_after=False)])

        _rows(
            _source(
                MockSession,
                endpoint="sessions",
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="updated_at",
            )
        )

        assert not any(k.endswith("[gt]") for k in params[0])

    @patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters(self, MockSession: MagicMock) -> None:
        # providers exposes no server-side timestamp filter; it must not fabricate one.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "pro_1"}], has_more_after=False)])

        _rows(
            _source(
                MockSession,
                endpoint="providers",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert params[0] == {"limit": DEFAULT_PAGE_SIZE, "order": "asc"}


class TestSourceResponse:
    @parameterized.expand(
        [
            # Pagination is by record id (order=asc). `updated_at` is not monotonic in id order, so
            # those syncs must run "desc" (the pipeline then commits the watermark only after a full
            # run). An "asc" claim here lets an interrupted sync advance the watermark past rows it
            # hasn't fetched, silently losing them from the warehouse.
            ("sessions_default_updated_at", "sessions", None, "desc"),
            ("provider_runs_default_updated_at", "provider_runs", None, "desc"),
            ("provider_deployments_default_updated_at", "provider_deployments", None, "desc"),
            # A user overriding sessions onto created_at makes per-batch checkpointing safe again.
            ("sessions_user_picks_created_at", "sessions", "created_at", "asc"),
            # created_at tracks id order, so append-only streams checkpoint safely per batch.
            ("session_messages_created_at", "session_messages", None, "asc"),
            ("tool_calls_created_at", "tool_calls", None, "asc"),
            # Full-refresh-only endpoint has no incremental field.
            ("providers_full_refresh", "providers", None, "asc"),
        ]
    )
    def test_sort_mode_matches_incremental_field(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_sort_mode: str
    ) -> None:
        response = metorial_source(
            api_key="metorial_sk_x",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            incremental_field=incremental_field,
        )
        assert response.sort_mode == expected_sort_mode
        assert response.primary_keys == ["id"]
        # Partition key must be the stable created_at, never updated_at (partitions would rewrite each sync).
        assert response.partition_keys == ["created_at"]


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @patch(CLIENT_SESSION_PATCH)
    def test_4xx_raises_matchable_http_error_without_leaking_key(
        self, _name: str, status: int, reason: str, MockSession: MagicMock
    ) -> None:
        # The secret key must never reach the exception text (surfaced as the schema's latest_error
        # outside warehouse ACLs), but the stable `<status> Client Error: <reason> for url:
        # https://api.metorial.com...` prefix that get_non_retryable_errors() matches on must survive.
        session = MockSession.return_value
        _wire(
            session,
            [_response(status=status, reason=reason, url=f"https://api.metorial.com/sessions?token={_SECRET_KEY}")],
        )

        with pytest.raises(HTTPError) as exc:
            _rows(_source(MockSession, endpoint="sessions", api_key=_SECRET_KEY))

        message = str(exc.value)
        assert _SECRET_KEY not in message
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.metorial.com/sessions")

    @parameterized.expand([("server_error", 503), ("rate_limited", 429)])
    @patch("time.sleep")
    @patch(CLIENT_SESSION_PATCH)
    def test_transient_status_is_retried(
        self, _name: str, status: int, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        # 429/5xx are transient: back off and retry rather than failing the sync.
        session = MockSession.return_value
        headers = {"Retry-After": "1"} if status == 429 else None
        _wire(
            session,
            [
                _response(status=status, reason="err", headers=headers),
                _response([{"id": "tcl_5"}], has_more_after=False),
            ],
        )

        rows = _rows(_source(MockSession))

        assert [r["id"] for r in rows] == ["tcl_5"]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @patch(METORIAL_SESSION_PATCH)
    def test_valid_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        mock_session_factory.return_value = session

        assert validate_credentials(_SECRET_KEY) is True
        # The key must be registered with the tracked transport so it's masked in logged URLs / samples.
        mock_session_factory.assert_called_once_with(redact_values=(_SECRET_KEY,))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @patch(METORIAL_SESSION_PATCH)
    def test_invalid_key(self, _name: str, status: int, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        mock_session_factory.return_value = session

        assert validate_credentials("bad-key") is False

    @patch(METORIAL_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("no network")
        mock_session_factory.return_value = session

        assert validate_credentials("key") is False
