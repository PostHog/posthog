import json
import base64
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet import (
    MAILJET_BASE_URL,
    MailjetResumeConfig,
    _to_unix_ts,
    mailjet_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    ENDPOINTS,
    MAILJET_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailjet module.
MAILJET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet.make_tracked_session"
)


def _response(rows: list[dict[str, Any]] | None, total: int | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_data:
        body["Data"] = rows or []
    if total is not None:
        body["Total"] = total
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b'{"ErrorMessage": "boom"}'
    return resp


def _make_manager(resume_state: MailjetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; capture each request's params and the request object AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy per page.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    requests_seen: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        requests_seen.append(request)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, requests_seen


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return mailjet_source("key", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


LIMIT = MAILJET_ENDPOINTS["contact"].page_size


class TestToUnixTs:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), 1767225600),
            ("naive_datetime", datetime(2026, 1, 1), 1767225600),
            ("int_passthrough", 1767225600, 1767225600),
            ("none", None, None),
            ("string", "not-a-ts", None),
        ]
    )
    def test_to_unix_ts(self, _name: str, value: object, expected: int | None) -> None:
        assert _to_unix_ts(value) == expected


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_wired_from_credentials(self, MockSession) -> None:
        session = MockSession.return_value
        _params, requests_seen = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(_source("contact", _make_manager()))

        auth = requests_seen[0].auth
        encoded = base64.b64encode(b"key:secret").decode()
        # HttpBasicAuth emits exactly `Basic base64(key:secret)`.
        assert auth.username == "key"
        assert auth.password == "secret"
        assert base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode() == encoded


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"ID": i} for i in range(3)], total=3)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 3
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_multi_page_advances_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response([{"ID": i} for i in range(LIMIT)], total=LIMIT + 2),
                _response([{"ID": i} for i in range(2)], total=LIMIT + 2),
            ],
        )

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == LIMIT + 2
        assert session.send.call_count == 2
        assert params[0]["Offset"] == 0
        assert params[0]["Limit"] == LIMIT
        assert params[1]["Offset"] == LIMIT

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_exact_multiple_terminates_via_total(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page whose length == limit but Total is reached must stop without a second request.
        _wire(session, [_response([{"ID": i} for i in range(LIMIT)], total=LIMIT)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == LIMIT
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total=0)])

        source = _source("contact", _make_manager())
        assert _rows(source) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_treated_as_empty(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, total=0, drop_data=True)])

        # A 200 body without "Data" is lenient — no rows, no raise (matches the prior implementation).
        source = _source("contact", _make_manager())
        assert _rows(source) == []
        assert session.send.call_count == 1

    @parameterized.expand([(name,) for name in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_param_sent(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(_source(endpoint, _make_manager()))

        assert params[0]["Sort"] == MAILJET_ENDPOINTS[endpoint].sort

    def test_campaigndraft_does_not_sort_on_created_at(self) -> None:
        # Regression guard for the Sort fallback documented in settings.py.
        assert MAILJET_ENDPOINTS["campaigndraft"].sort == "ID"


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=2000)])

        manager = _make_manager(MailjetResumeConfig(offset=1000, endpoint="contact"))
        _rows(_source("contact", manager))

        assert params[0]["Offset"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_ignored_for_other_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        manager = _make_manager(MailjetResumeConfig(offset=1000, endpoint="campaign"))
        _rows(_source("contact", manager))

        assert params[0]["Offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"ID": i} for i in range(3)], total=3)])

        manager = _make_manager()
        _rows(_source("contact", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_saved_after_each_page_with_successor(self, MockSession) -> None:
        # State is persisted after every page that has a successor, carrying the next offset and the
        # endpoint. The final page saves nothing (sync is complete). A crash re-yields the last page,
        # which merge dedupes on the primary key.
        session = MockSession.return_value
        _wire(
            session,
            [_response([{"ID": i} for i in range(p * LIMIT, (p + 1) * LIMIT)], total=3 * LIMIT) for p in range(3)],
        )

        manager = _make_manager()
        rows = _rows(_source("contact", manager))

        assert len(rows) == 3 * LIMIT
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [s.offset for s in saved] == [LIMIT, 2 * LIMIT]
        assert all(s.endpoint == "contact" for s in saved)


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_applied_for_statistics_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "openinformation",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["FromTS"] == 1767225600

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_not_applied_for_full_refresh_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "contact",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "FromTS" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_from_ts_not_applied_without_incremental_flag(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"ID": 1}], total=1)])

        _rows(
            _source(
                "openinformation",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "FromTS" not in params[0]


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = MAILJET_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_retries_until_success(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(429), _response([{"ID": 1}], total=1)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 1
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_500_retries_until_success(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(500), _response([{"ID": 1}], total=1)])

        rows = _rows(_source("contact", _make_manager()))

        assert len(rows) == 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_does_not_retry_and_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(401)])

        with pytest.raises(Exception):
            _rows(_source("contact", _make_manager()))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok_200", 200, True), ("unauthorized_401", 401, False), ("server_500", 500, False)])
    @mock.patch(MAILJET_SESSION_PATCH)
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("key", "secret") is expected

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{MAILJET_BASE_URL}/contactmetadata?Limit=1"
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        token = headers["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:secret"

    @mock.patch(MAILJET_SESSION_PATCH)
    def test_validate_credentials_network_error_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False
