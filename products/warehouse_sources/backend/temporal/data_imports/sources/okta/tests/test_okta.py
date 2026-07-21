import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.okta import okta as okta_module
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
    OktaResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    normalize_domain,
    okta_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import OKTA_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(items: Optional[list[dict[str, Any]]], *, status_code: int = 200, link: Optional[str] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items if items is not None else []).encode()
    if link:
        resp.headers["Link"] = link
    return resp


def _redirect_response(status_code: int = 302, location: str = "https://internal.example/") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _make_manager(resume_state: Optional[OktaResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("example.okta.com", "example.okta.com"),
            ("https://example.okta.com", "example.okta.com"),
            ("http://example.okta.com/", "example.okta.com"),
            ("  example.okta.com  ", "example.okta.com"),
            ("example.okta.com/api/v1", "example.okta.com"),
            ("https://example.okta.com/api/v1/users", "example.okta.com"),
        ],
    )
    def test_normalize_domain(self, raw, expected):
        assert normalize_domain(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self):
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildInitialParams:
    def test_filter_endpoint_incremental(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert params["filter"] == 'lastUpdated gt "2024-01-01T00:00:00.000Z"'
        assert params["limit"] == 200

    def test_applications_never_sends_filter(self):
        # Okta's Apps API `filter` does not support lastUpdated, so an incremental run must
        # not send a server-side filter — it would 400.
        params = _build_initial_params(
            OKTA_ENDPOINTS["applications"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert params == {"limit": 200}

    def test_filter_endpoint_no_watermark_has_no_filter(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="lastUpdated",
        )
        assert "filter" not in params

    def test_filter_endpoint_full_refresh_has_no_filter(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["groups"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert "filter" not in params

    def test_logs_incremental_uses_since(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="published",
        )
        assert params["since"] == "2024-01-01T00:00:00.000Z"
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_first_sync_applies_lookback(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="published",
        )
        # The 90-day lookback means `since` is populated even without a stored watermark.
        assert "since" in params
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_full_refresh_has_no_since(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert "since" not in params
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_full_refresh_ignores_stray_watermark(self):
        # Even if a watermark leaks in, a non-incremental run must not apply a `since` filter.
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert "since" not in params

    def test_non_incremental_endpoint_only_limit(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["group_rules"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert params == {"limit": 200}


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(okta_module, "make_tracked_session", return_value=session)

    def _resp(self, *, status_code=200, json_data=None, text=""):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        response.json.return_value = json_data
        return response

    def test_success(self):
        with self._patch_session(self._resp(status_code=200)):
            assert validate_credentials("example.okta.com", "tok") == (True, None)

    def test_invalid_token(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert "Invalid Okta API token" == msg

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._resp(status_code=403)):
            assert validate_credentials("example.okta.com", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._resp(status_code=403)):
            valid, msg = validate_credentials("example.okta.com", "tok", schema_name="users")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_domain", ["", "not a domain!", "https://"])
    def test_invalid_domain_short_circuits(self, bad_domain):
        valid, msg = validate_credentials(bad_domain, "tok")
        assert valid is False
        assert msg == "Invalid Okta domain"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be rejected,
        # not followed (SSRF).
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert msg == okta_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(okta_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestOktaSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_key, partition_key",
        [
            ("users", "id", "created"),
            ("groups", "id", "created"),
            ("applications", "id", "created"),
            ("logs", "uuid", "published"),
            ("group_rules", "id", "created"),
            ("user_types", "id", None),
        ],
    )
    def test_response_shape(self, endpoint, primary_key, partition_key):
        response = okta_source(
            domain="example.okta.com",
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestOktaPagination:
    def _source(self, endpoint="users", manager=None, **kwargs):
        return okta_source(
            domain="example.okta.com",
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager if manager is not None else _make_manager(),
            **kwargs,
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_header_across_pages(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response(
                    [{"id": "1"}, {"id": "2"}],
                    link='<https://example.okta.com/api/v1/users?after=cur>; rel="next"',
                ),
                _response([{"id": "3"}]),
            ],
        )
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert snaps[0]["url"] == "https://example.okta.com/api/v1/users"
        assert snaps[0]["params"]["limit"] == 200
        # Second request follows the self-contained Link-header URL.
        assert snaps[1]["url"] == "https://example.okta.com/api/v1/users?after=cur"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], link='<https://example.okta.com/api/v1/users?after=cur>; rel="next"'),
                _response([{"id": "2"}]),
            ],
        )
        manager = _make_manager()
        _rows(self._source(manager=manager))

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, OktaResumeConfig)
        assert saved.next_url == "https://example.okta.com/api/v1/users?after=cur"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "9"}])])
        manager = _make_manager(OktaResumeConfig(next_url="https://example.okta.com/api/v1/users?after=resume"))
        rows = _rows(self._source(manager=manager))

        assert snaps[0]["url"] == "https://example.okta.com/api/v1/users?after=resume"
        assert [r["id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_even_with_next_link(self, MockSession):
        # The System Log always returns a next link, so an empty page must end pagination.
        session = MockSession.return_value
        _wire(session, [_response([], link='<https://example.okta.com/api/v1/logs?after=x>; rel="next"')])
        rows = _rows(self._source(endpoint="logs"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_next_url_on_foreign_host(self, MockSession):
        # A server-controlled Link header pointing off-org must not be followed (SSRF guard).
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], link='<http://169.254.169.254/latest/meta-data/>; rel="next"')])
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ignores_resume_url_on_foreign_host(self, MockSession):
        # A poisoned resume URL must fall back to the initial org URL, not be followed.
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "1"}])])
        manager = _make_manager(OktaResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))
        rows = _rows(self._source(manager=manager))

        assert snaps[0]["url"].startswith("https://example.okta.com/api/v1/users")
        assert [r["id"] for r in rows] == ["1"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession):
        # Requests disable redirect following, and a redirect response is rejected rather than
        # followed to a (potentially internal) Location (SSRF).
        session = MockSession.return_value
        _wire(session, [_redirect_response(302)])
        with pytest.raises(ValueError):
            _rows(self._source())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_reaches_request(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "1"}])])
        _rows(
            self._source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="lastUpdated",
            )
        )
        assert snaps[0]["params"]["filter"] == 'lastUpdated gt "2024-01-01T00:00:00.000Z"'
        assert snaps[0]["params"]["limit"] == 200

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(session, [_response([], status_code=429), _response([{"id": "1"}])])
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_runtime_host_check_blocks_unsafe_domain(self, MockSession):
        # The configured domain is re-checked at run time (DNS rebinding) before any request.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])
        with mock.patch.object(okta_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(okta_module.OktaHostNotAllowedError):
                _rows(self._source())
        session.send.assert_not_called()
