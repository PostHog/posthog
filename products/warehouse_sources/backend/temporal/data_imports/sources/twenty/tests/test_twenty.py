import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.twenty import twenty as twenty_module
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.settings import TWENTY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.twenty import (
    TwentyHostNotAllowedError,
    TwentyResumeConfig,
    _format_filter_value,
    normalize_base_url,
    twenty_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(*, status_code: int = 200, body: Any = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode() if body is not None else b""
    return resp


def _page(
    rows: list[dict[str, Any]],
    *,
    object_name: str = "companies",
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> Response:
    body: dict[str, Any] = {
        "data": {object_name: rows},
        "totalCount": len(rows),
        "pageInfo": {"hasNextPage": has_next_page, "startCursor": None, "endCursor": end_cursor},
    }
    return _response(body=body)


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; delegate prepare_request to a real session so auth + params are applied.

    The framework mutates a single request/params dict in place across pages, so we snapshot each
    prepared request (its URL carries the limit/starting_after query and its headers carry the
    auth) as the client prepares it, then return canned responses from ``send``.
    """
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        real.headers.clear()
        real.headers.update(session.headers)
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _make_manager(resume_state: TwentyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(
    manager: mock.MagicMock,
    *,
    base_url: str | None = None,
    endpoint: str = "companies",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Any:
    return twenty_source(
        base_url=base_url,
        api_key="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _query(prepared: requests.PreparedRequest) -> dict[str, list[str]]:
    assert prepared.url is not None
    return parse_qs(urlparse(prepared.url).query)


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://api.twenty.com"),
            ("", "https://api.twenty.com"),
            ("   ", "https://api.twenty.com"),
            ("https://api.twenty.com", "https://api.twenty.com"),
            ("https://api.twenty.com/", "https://api.twenty.com"),
            ("https://api.twenty.com/rest", "https://api.twenty.com"),
            ("twenty.example.com", "https://twenty.example.com"),
            ("http://twenty.example.com/", "http://twenty.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestHostOf:
    @pytest.mark.parametrize(
        "url, expected_host",
        [
            ("https://twenty.example.com", "twenty.example.com"),
            # A backslash — literal or `%5c`-encoded — is an SSRF vector: `urlparse` and
            # requests/urllib3 disagree on the host, so the check could validate a decoy host while
            # the request reaches an internal address. No legitimate URL contains one, so `_host_of`
            # fails closed and returns "" (rejected upstream).
            ("https://safe.com\\@169.254.169.254", ""),
            ("https://safe.com%5c@169.254.169.254", ""),
            ("https://safe.com%5C@169.254.169.254", ""),
        ],
    )
    def test_host_rejects_backslash_ssrf_bypass(self, url, expected_host):
        assert twenty_module._host_of(url) == expected_host


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC), "2024-01-01T12:30:00.000Z"),
            (datetime(2024, 1, 1, 12, 30, 0), "2024-01-01T12:30:00.000Z"),
            (date(2024, 1, 1), "2024-01-01"),
            ("2024-01-01T00:00:00.000Z", "2024-01-01T00:00:00.000Z"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_filter_value(value) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(twenty_module, "make_tracked_session", return_value=session)

    def _resp(self, *, status_code=200):
        response = mock.MagicMock()
        response.status_code = status_code
        return response

    def test_success(self):
        with self._patch_session(self._resp(status_code=200)):
            assert validate_credentials(None, "tok", team_id=1) == (True, None)

    def test_invalid_key_401(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials(None, "tok", team_id=1)
            assert valid is False
            assert "Invalid Twenty API key" in (msg or "")

    def test_permission_403_at_source_create_is_accepted(self):
        with self._patch_session(self._resp(status_code=403)):
            assert validate_credentials(None, "tok", team_id=1, schema_name=None) == (True, None)

    def test_permission_403_for_scoped_probe_fails(self):
        with self._patch_session(self._resp(status_code=403)):
            valid, msg = validate_credentials(None, "tok", team_id=1, schema_name="companies")
            assert valid is False
            assert msg is not None

    def test_unexpected_status(self):
        with self._patch_session(self._resp(status_code=500)):
            valid, msg = validate_credentials(None, "tok", team_id=1)
            assert valid is False
            assert "500" in (msg or "")

    def test_request_exception_returns_failure(self):
        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "tok", team_id=1)
            assert valid is False
            assert "Could not reach" in (msg or "")

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(twenty_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_rejects_plaintext_http_before_sending_token(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            valid, msg = validate_credentials("http://twenty.example.com", "tok", team_id=1)
            assert valid is False
            assert msg == twenty_module.HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host_with_bearer_token(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials("https://twenty.example.com", "tok", team_id=1)
            call = patched.return_value.get.call_args
            assert call.args[0] == "https://twenty.example.com/rest/companies?limit=1"
            assert call.kwargs["headers"]["Authorization"] == "Bearer tok"
            assert call.kwargs["allow_redirects"] is False

    def test_redacts_token_in_telemetry(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials(None, "tok", team_id=1)
            assert patched.call_args.kwargs["redact_values"] == ("tok",)


class TestTwentySourceResponse:
    @pytest.mark.parametrize("endpoint", list(TWENTY_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_cursor(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(
            session,
            [
                _page([{"id": "1"}, {"id": "2"}], has_next_page=True, end_cursor="cursor-a"),
                _page([{"id": "3"}], has_next_page=False, end_cursor="cursor-b"),
            ],
        )
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert "starting_after" not in _query(prepared[0])
        assert _query(prepared[1])["starting_after"] == ["cursor-a"]
        assert _query(prepared[0])["limit"] == ["200"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_next_page_false_despite_end_cursor(self, MockSession):
        # Twenty's final page can still carry a non-null endCursor pointing at its own last row;
        # hasNextPage is the real termination signal and must win over cursor presence.
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], has_next_page=False, end_cursor="cursor-last")])
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_does_not_advance(self, MockSession):
        # A broken or hostile host can return hasNextPage=true with the same endCursor forever;
        # the sync must stop rather than loop until the week-long activity timeout. Only two
        # responses are wired, so a third request would raise instead of looping silently.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "1"}], has_next_page=True, end_cursor="cursor-a"),
                _page([{"id": "2"}], has_next_page=True, end_cursor="cursor-a"),
            ],
        )
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "1"}], has_next_page=True, end_cursor="cursor-a"),
                _page([{"id": "2"}], has_next_page=False, end_cursor="cursor-b"),
            ],
        )
        manager = _make_manager()
        _rows(_source(manager))

        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, TwentyResumeConfig)
        assert saved.starting_after == "cursor-a"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "9"}], has_next_page=False)])
        manager = _make_manager(TwentyResumeConfig(starting_after="cursor-a"))
        rows = _rows(_source(manager))

        assert _query(prepared[0])["starting_after"] == ["cursor-a"]
        assert [r["id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([], has_next_page=False)])
        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_passes_allow_redirects_false(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}])])
        _rows(_source(_make_manager()))
        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_bearer_token(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}])])
        _rows(_source(_make_manager()))
        assert prepared[0].headers["Authorization"] == "Bearer tok"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redacts_token_in_telemetry(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}])])
        _rows(_source(_make_manager()))
        assert MockSession.call_args.kwargs["redact_values"] == ("tok",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}])])
        with mock.patch.object(twenty_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(TwentyHostNotAllowedError):
                _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_plaintext_http(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}])])
        with pytest.raises(TwentyHostNotAllowedError):
            _rows(_source(_make_manager(), base_url="http://twenty.example.com"))

    @pytest.mark.parametrize("status_code", [429, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _sleep, status_code):
        session = MockSession.return_value
        _wire(session, [_response(status_code=status_code), _page([{"id": "r1"}])])
        rows = _rows(_source(_make_manager()))
        assert [r["id"] for r in rows] == ["r1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sorts_by_id(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}])])
        _rows(_source(_make_manager(), should_use_incremental_field=False))
        assert _query(prepared[0])["order_by"] == ["id[AscNullsFirst]"]
        assert "filter" not in _query(prepared[0])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sorts_and_filters_by_chosen_field(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}])])
        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field="createdAt",
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        query = _query(prepared[0])
        assert query["order_by"] == ["createdAt[AscNullsFirst]"]
        assert query["filter"] == ['createdAt[gte]:"2024-01-01T00:00:00.000Z"']

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_first_sync_omits_filter(self, MockSession):
        # No watermark yet (first incremental sync): the filter param is dropped entirely rather
        # than sending a malformed value, so the full history is pulled.
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}])])
        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field="updatedAt",
                db_incremental_field_last_value=None,
            )
        )
        query = _query(prepared[0])
        assert query["order_by"] == ["updatedAt[AscNullsFirst]"]
        assert "filter" not in query

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_defaults_to_updated_at_when_field_unset(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}])])
        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field=None,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        query = _query(prepared[0])
        assert query["order_by"] == ["updatedAt[AscNullsFirst]"]

    @pytest.mark.parametrize("endpoint,object_name", [("activities", "timelineActivities"), ("companies", "companies")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_data_selector_matches_object_name_plural(self, MockSession, endpoint, object_name):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], object_name=object_name)])
        rows = _rows(_source(_make_manager(), endpoint=endpoint))
        assert [r["id"] for r in rows] == ["1"]
