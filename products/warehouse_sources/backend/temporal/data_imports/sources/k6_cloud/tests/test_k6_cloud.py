import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud import (
    K6_CLOUD_BASE_URL,
    K6CloudResumeConfig,
    _absolute_url,
    _format_rfc3339,
    k6_cloud_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the k6_cloud module.
K6_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud.make_tracked_session"
)


def _response(
    url: str,
    value: Optional[list[dict[str, Any]]] = None,
    *,
    next_link: Optional[str] = None,
    drop_value: bool = False,
    status: int = 200,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_value:
        body["value"] = value or []
    if next_link is not None:
        body["@nextLink"] = next_link
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: K6CloudResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; return (param_snapshots, url_snapshots) captured AT SEND TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so snapshotting a copy
    when each request is prepared is the only way to see per-page state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return k6_cloud_source(
        api_token="tok",
        stack_id="1",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("microseconds", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result


class TestAbsoluteUrl:
    @parameterized.expand(
        [
            (
                "absolute_https",
                "https://api.k6.io/cloud/v6/test_runs",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
            (
                "relative_path",
                "https://api.k6.io/cloud/v6/test_runs",
                "/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
        ]
    )
    def test_absolute_url(self, _name: str, current: str, next_link: str, expected: str) -> None:
        assert _absolute_url(current, next_link) == expected

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/steal"),
            ("relative_to_other_host", "//evil.example.com/steal"),
            ("http_scheme", "http://api.k6.io/cloud/v6/test_runs"),
        ]
    )
    def test_rejects_non_k6_next_link(self, _name: str, next_link: str) -> None:
        # A tampered `@nextLink` must never redirect the credential-bearing request off the k6 origin.
        with pytest.raises(ValueError):
            _absolute_url("https://api.k6.io/cloud/v6/test_runs", next_link)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_progresses(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        base = "https://api.k6.io/cloud/v6/test_runs"
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        _params, urls = _wire(
            session,
            [
                _response(base, [{"id": 1}, {"id": 2}], next_link=next_url),
                _response(next_url, [{"id": 3}], next_link=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("test_runs", manager))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # Second request follows the @nextLink URL rather than re-hitting the base path.
        assert urls[0] == base
        assert urls[1] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_param_present_for_paginated_endpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/test_runs", [{"id": 1}])])

        _rows(_source("test_runs", _make_manager()))
        assert params[0]["$top"] == "1000"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_load_zones_has_no_top_param(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/load_zones", [{"id": 1}])])

        _rows(_source("load_zones", _make_manager()))
        assert "$top" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_sends_orderby(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/projects", [{"id": 1}])])

        _rows(_source("projects", _make_manager()))
        assert params[0]["$orderby"] == "created"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_test_runs_never_sends_orderby(self, MockSession: mock.MagicMock) -> None:
        # The top-level test_runs endpoint rejects $orderby, so it must never be sent there.
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/test_runs", [{"id": 1}])])

        _rows(_source("test_runs", _make_manager()))
        assert "$orderby" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_reads_single_page_and_ignores_next_link(self, MockSession: mock.MagicMock) -> None:
        # load_zones returns everything in one response; even a stray @nextLink must not be followed.
        session = MockSession.return_value
        _wire(
            session,
            [_response("https://api.k6.io/cloud/v6/load_zones", [{"id": 1}, {"id": 2}], next_link="ignored")],
        )

        manager = _make_manager()
        rows = _rows(_source("load_zones", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_value_key_raises_loudly(self, MockSession: mock.MagicMock) -> None:
        # A 200 body without `value` is an unexpected shape — fail loud rather than empty the table.
        session = MockSession.return_value
        _wire(session, [_response("https://api.k6.io/cloud/v6/load_zones", drop_value=True)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("load_zones", _make_manager()))


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_created_after_added_when_last_value_present(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/test_runs", [{"id": 1}])])

        _rows(
            _source(
                "test_runs",
                _make_manager(),
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )
        assert params[0]["created_after"] == "2026-03-04T02:58:14.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_time_filter_on_full_refresh(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/test_runs", [{"id": 1}])])

        _rows(_source("test_runs", _make_manager(), db_incremental_field_last_value=None))
        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_never_sends_time_filter(self, MockSession: mock.MagicMock) -> None:
        # Projects has no server-side time filter, so a passed-in watermark must not add one.
        session = MockSession.return_value
        params, _urls = _wire(session, [_response("https://api.k6.io/cloud/v6/projects", [{"id": 1}])])

        _rows(_source("projects", _make_manager(), db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC)))
        assert "created_after" not in params[0]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_except_last(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        base = "https://api.k6.io/cloud/v6/test_runs"
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        _wire(
            session,
            [
                _response(base, [{"id": 1}], next_link=next_url),
                _response(next_url, [{"id": 2}], next_link=None),
            ],
        )

        manager = _make_manager()
        _rows(_source("test_runs", manager))

        # State is saved once (pointing at the next page); the final page has no link to persist.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [K6CloudResumeConfig(next_url=next_url)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_link(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_url = "https://api.k6.io/cloud/v6/test_runs?$skip=2000&$top=1000"
        _params, urls = _wire(session, [_response(resume_url, [{"id": 9}], next_link=None)])

        manager = _make_manager(K6CloudResumeConfig(next_url=resume_url))
        rows = _rows(_source("test_runs", manager))

        assert rows == [{"id": 9}]
        # The first (only) request goes straight to the saved next link, not the base path.
        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_poisoned_resume_url(self, MockSession: mock.MagicMock) -> None:
        # Resume state is loaded from Redis; a poisoned next link must not leak credentials off-origin.
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(K6CloudResumeConfig(next_url="https://evil.example.com/steal"))
        with pytest.raises(ValueError):
            _rows(_source("test_runs", manager))


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        url = "https://api.k6.io/cloud/v6/test_runs"
        _wire(session, [_response(url, status=status), _response(url, [{"id": 1}], next_link=None)])

        rows = _rows(_source("test_runs", _make_manager()))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_immediately(self, MockSession: mock.MagicMock) -> None:
        # A 401 is not retryable — raise_for_status surfaces it on the first attempt.
        session = MockSession.return_value
        _wire(session, [_response("https://api.k6.io/cloud/v6/test_runs", status=401)])

        with pytest.raises(HTTPError):
            _rows(_source("test_runs", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, (True, False)),
            ("bad_token", 401, None, (False, False)),
            ("forbidden", 403, None, (False, True)),
            ("forbidden_schema", 403, "test_runs", (False, True)),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, schema_name: str | None, expected: tuple[bool, bool]
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        with mock.patch(K6_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = response
            assert validate_credentials("tok", "1", schema_name) == expected

    def test_network_error_is_invalid_not_forbidden(self) -> None:
        with mock.patch(K6_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("tok", "1") == (False, False)

    def test_schemaless_probe_hits_auth_endpoint(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        with mock.patch(K6_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = response
            validate_credentials("tok", "1")
        assert mock_session.return_value.get.call_args[0][0] == f"{K6_CLOUD_BASE_URL}/auth"
