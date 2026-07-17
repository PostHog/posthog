import itertools
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.infisical import infisical as infisical_module
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.infisical import (
    INVALID_CREDENTIALS_ERROR,
    InfisicalAuthError,
    InfisicalResponseTooLargeError,
    InfisicalResumeConfig,
    _format_incremental_value,
    _parse_retry_after,
    _retry_wait,
    get_rows,
    infisical_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.settings import INFISICAL_ENDPOINTS

LOGIN_JSON = {"accessToken": "tok", "expiresIn": 3600, "accessTokenMaxTTL": 7200, "tokenType": "Bearer"}


def _response(
    *, status_code: int = 200, json_data: Any = None, text: str = "", body_chunks: Optional[list[bytes]] = None
) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.headers = {}
    response.json.return_value = json_data
    # _send streams the body and drains it with single reads (read1), so the response's raw
    # stream must hand back the chunks then an empty read to signal EOF.
    chunks = body_chunks if body_chunks is not None else [text.encode("utf-8")]
    response.raw = mock.MagicMock()
    response.raw.read1.side_effect = [*chunks, b""]
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
    return response


def _login_response() -> mock.MagicMock:
    return _response(json_data=LOGIN_JSON)


def _run_get_rows(
    responses: list[Any],
    endpoint: str,
    manager: Optional[mock.MagicMock] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[dict[str, Any]], mock.MagicMock, mock.MagicMock]:
    if manager is None:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
    session = mock.MagicMock()
    session.request.side_effect = responses
    with (
        mock.patch.object(infisical_module, "make_tracked_session", return_value=session),
        mock.patch.object(infisical_module, "_is_host_safe", return_value=(True, None)),
    ):
        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            base_url="https://app.infisical.com",
            client_id="cid",
            client_secret="csecret",
            organization_id="org-123",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
            team_id=1,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
    return rows, session, manager


def _get_urls(session: mock.MagicMock) -> list[str]:
    return [call.args[1] for call in session.request.call_args_list if call.args[0] == "get"]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("app.infisical.com", "https://app.infisical.com"),
            ("https://eu.infisical.com/", "https://eu.infisical.com"),
            ("  https://app.infisical.com/api/v1  ", "https://app.infisical.com"),
            ("http://secrets.example.com:8443/some/path", "https://secrets.example.com:8443"),
            ("HTTPS://Secrets.Example.COM", "https://secrets.example.com"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize("bad", ["", "https://", "not a url!", "https://bad_host/"])
    def test_rejects_invalid(self, bad):
        with pytest.raises(ValueError):
            normalize_base_url(bad)


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestAuditLogRows:
    def test_incremental_run_windows_and_paginates(self):
        audit_config = INFISICAL_ENDPOINTS["audit_logs"]
        page1 = _response(json_data={"auditLogs": [{"id": "3"}, {"id": "2"}, {"id": "1"}]})
        page2 = _response(json_data={"auditLogs": [{"id": "0"}]})
        with mock.patch.object(audit_config, "page_limit", 3):
            rows, session, manager = _run_get_rows(
                [_login_response(), page1, page2],
                "audit_logs",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )

        assert [r["id"] for r in rows] == ["3", "2", "1", "0"]

        first, second = (_query(u) for u in _get_urls(session))
        assert first["startDate"] == ["2024-01-01T00:00:00.000Z"]
        assert first["offset"] == ["0"]
        assert second["offset"] == ["3"]
        # endDate is pinned at sync start so offset pagination stays stable while new logs arrive.
        assert first["endDate"] == second["endDate"]
        # A short page terminates pagination.
        assert len(_get_urls(session)) == 2

        saved_offsets = [call.args[0].offset for call in manager.save_state.call_args_list]
        assert saved_offsets == [3, 4]

    def test_full_refresh_has_no_start_date(self):
        page = _response(json_data={"auditLogs": [{"id": "1"}]})
        _rows, session, _manager = _run_get_rows([_login_response(), page], "audit_logs")

        params = _query(_get_urls(session)[0])
        assert "startDate" not in params
        assert "endDate" in params

    def test_resumes_saved_window_and_offset(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = InfisicalResumeConfig(
            offset=7, window_start="2024-01-01T00:00:00.000Z", window_end="2024-06-01T00:00:00.000Z"
        )
        page = _response(json_data={"auditLogs": [{"id": "1"}]})
        _rows, session, _manager = _run_get_rows([_login_response(), page], "audit_logs", manager=manager)

        params = _query(_get_urls(session)[0])
        assert params["offset"] == ["7"]
        assert params["startDate"] == ["2024-01-01T00:00:00.000Z"]
        assert params["endDate"] == ["2024-06-01T00:00:00.000Z"]

    def test_empty_first_page_yields_nothing(self):
        page = _response(json_data={"auditLogs": []})
        rows, _session, manager = _run_get_rows([_login_response(), page], "audit_logs")

        assert rows == []
        manager.save_state.assert_not_called()


class TestOffsetPaginatedRows:
    def test_identities_paginates_with_stable_sort(self):
        identities_config = INFISICAL_ENDPOINTS["identities"]
        page1 = _response(json_data={"identityMemberships": [{"id": "a"}, {"id": "b"}]})
        page2 = _response(json_data={"identityMemberships": [{"id": "c"}]})
        with mock.patch.object(identities_config, "page_limit", 2):
            rows, session, manager = _run_get_rows([_login_response(), page1, page2], "identities")

        assert [r["id"] for r in rows] == ["a", "b", "c"]

        urls = _get_urls(session)
        assert all("/api/v2/organizations/org-123/identity-memberships" in u for u in urls)
        first, second = (_query(u) for u in urls)
        assert first["orderBy"] == ["name"]
        assert first["orderDirection"] == ["asc"]
        assert first["offset"] == ["0"]
        assert second["offset"] == ["2"]
        assert [call.args[0].offset for call in manager.save_state.call_args_list] == [2, 3]


class TestUnpaginatedRows:
    @pytest.mark.parametrize(
        "endpoint, path, data_key",
        [
            ("projects", "/api/v1/projects", "projects"),
            ("organization_memberships", "/api/v2/organizations/org-123/memberships", "users"),
        ],
    )
    def test_single_request_list(self, endpoint, path, data_key):
        page = _response(json_data={data_key: [{"id": "1", "orgId": "org-123"}, {"id": "2", "orgId": "org-123"}]})
        rows, session, _manager = _run_get_rows([_login_response(), page], endpoint)

        assert [r["id"] for r in rows] == ["1", "2"]
        urls = _get_urls(session)
        assert len(urls) == 1
        assert urlparse(urls[0]).path == path


class TestProjectMembershipsFanOut:
    def test_fans_out_over_projects_and_skips_forbidden(self):
        projects = _response(
            json_data={
                "projects": [
                    {"id": "p1", "orgId": "org-123"},
                    {"id": "p2", "orgId": "org-123"},
                    {"id": "p3", "orgId": "org-123"},
                ]
            }
        )
        memberships_p1 = _response(json_data={"memberships": [{"id": "m1", "projectId": "p1"}]})
        memberships_p2 = _response(status_code=403)
        memberships_p3 = _response(json_data={"memberships": [{"id": "m2", "projectId": "p3"}]})
        rows, session, _manager = _run_get_rows(
            [_login_response(), projects, memberships_p1, memberships_p2, memberships_p3],
            "project_memberships",
        )

        # The 403 project is skipped (per-project grants), the rest still sync.
        assert [r["id"] for r in rows] == ["m1", "m2"]
        paths = [urlparse(u).path for u in _get_urls(session)]
        assert paths == [
            "/api/v1/projects",
            "/api/v1/projects/p1/memberships",
            "/api/v1/projects/p2/memberships",
            "/api/v1/projects/p3/memberships",
        ]

    def test_non_permission_error_fails_the_sync(self):
        projects = _response(json_data={"projects": [{"id": "p1", "orgId": "org-123"}]})
        bad_request = _response(status_code=400)
        with pytest.raises(requests.HTTPError):
            _run_get_rows([_login_response(), projects, bad_request], "project_memberships")


class TestOrgScoping:
    # /api/v1/projects isn't org-scoped — a machine identity shared with several orgs sees them
    # all. Without the orgId filter, the projects table and the project_memberships fan-out would
    # leak project and membership data from orgs other than the configured one.
    def test_projects_table_excludes_other_orgs(self):
        page = _response(json_data={"projects": [{"id": "p1", "orgId": "org-123"}, {"id": "p2", "orgId": "other-org"}]})
        rows, _session, _manager = _run_get_rows([_login_response(), page], "projects")
        assert [r["id"] for r in rows] == ["p1"]

    def test_project_memberships_fan_out_skips_other_orgs(self):
        projects = _response(
            json_data={"projects": [{"id": "p1", "orgId": "org-123"}, {"id": "p2", "orgId": "other-org"}]}
        )
        memberships_p1 = _response(json_data={"memberships": [{"id": "m1", "projectId": "p1"}]})
        rows, session, _manager = _run_get_rows([_login_response(), projects, memberships_p1], "project_memberships")
        assert [r["id"] for r in rows] == ["m1"]
        # Only the configured org's project is ever fetched; the foreign project is skipped.
        paths = [urlparse(u).path for u in _get_urls(session)]
        assert paths == ["/api/v1/projects", "/api/v1/projects/p1/memberships"]


class TestTokenHandling:
    def test_logs_in_once_across_pages(self):
        page1 = _response(json_data={"auditLogs": [{"id": "1"}]})
        _rows, session, _manager = _run_get_rows([_login_response(), page1], "audit_logs")

        logins = [call for call in session.request.call_args_list if call.args[0] == "post"]
        assert len(logins) == 1
        assert logins[0].args[1] == "https://app.infisical.com/api/v1/auth/universal-auth/login"
        assert logins[0].kwargs["json"] == {"clientId": "cid", "clientSecret": "csecret"}

    def test_relogins_once_when_token_rejected_mid_sync(self):
        rejected = _response(status_code=401)
        page = _response(json_data={"projects": [{"id": "1", "orgId": "org-123"}]})
        rows, session, _manager = _run_get_rows([_login_response(), rejected, _login_response(), page], "projects")

        assert [r["id"] for r in rows] == ["1"]
        logins = [call for call in session.request.call_args_list if call.args[0] == "post"]
        assert len(logins) == 2

    def test_both_sessions_disable_sample_capture(self):
        # Sample capture reads response.text inside the adapter before _send's size cap runs,
        # so both sessions must ride capture-disabled adapters to keep an unbounded body from
        # a customer-controlled host out of memory. The auth body additionally carries the
        # client secret and minted accessToken in camelCase fields the name-based scrubbers
        # don't recognise. The secret is value-redacted on every session.
        data_session, auth_session = mock.MagicMock(), mock.MagicMock()
        auth_session.request.side_effect = [_login_response()]
        data_session.request.side_effect = [_response(json_data={"projects": [{"id": "1", "orgId": "org-123"}]})]
        factory = mock.MagicMock(side_effect=[data_session, auth_session])
        with (
            mock.patch.object(infisical_module, "make_tracked_session", factory),
            mock.patch.object(infisical_module, "_is_host_safe", return_value=(True, None)),
        ):
            rows = [
                row
                for batch in get_rows(
                    base_url="https://app.infisical.com",
                    client_id="cid",
                    client_secret="csecret",
                    organization_id="org-123",
                    endpoint="projects",
                    logger=mock.MagicMock(),
                    resumable_source_manager=mock.MagicMock(),
                    team_id=1,
                )
                for row in batch
            ]

        assert rows == [{"id": "1", "orgId": "org-123"}]
        data_session_kwargs, auth_session_kwargs = (call.kwargs for call in factory.call_args_list)
        assert data_session_kwargs["capture"] is False
        assert auth_session_kwargs["capture"] is False
        assert "csecret" in auth_session_kwargs["redact_values"]
        assert "csecret" in data_session_kwargs["redact_values"]
        # Only the login POST goes through the capture-disabled session.
        assert [call.args[0] for call in auth_session.request.call_args_list] == ["post"]
        assert [call.args[0] for call in data_session.request.call_args_list] == ["get"]

    def test_requests_never_follow_redirects(self):
        page = _response(json_data={"projects": [{"id": "1"}]})
        _rows, session, _manager = _run_get_rows([_login_response(), page], "projects")

        assert all(call.kwargs["allow_redirects"] is False for call in session.request.call_args_list)

    def test_rejects_unsafe_host_before_any_request(self):
        session = mock.MagicMock()
        with (
            mock.patch.object(infisical_module, "make_tracked_session", return_value=session),
            mock.patch.object(infisical_module, "_is_host_safe", return_value=(False, "internal address")),
        ):
            with pytest.raises(infisical_module.InfisicalHostNotAllowedError):
                list(
                    get_rows(
                        base_url="https://10.0.0.1",
                        client_id="cid",
                        client_secret="csecret",
                        organization_id="org-123",
                        endpoint="projects",
                        logger=mock.MagicMock(),
                        resumable_source_manager=mock.MagicMock(),
                        team_id=1,
                    )
                )
        session.request.assert_not_called()


class TestResponseLimits:
    def test_oversized_response_is_rejected(self):
        # base_url is customer-controlled, so an unbounded body must abort rather than buffer
        # into memory and exhaust the worker.
        oversized = _response(json_data={"projects": []}, body_chunks=[b"x" * 2048])
        with mock.patch.object(infisical_module, "MAX_RESPONSE_BYTES", 1024):
            with pytest.raises(InfisicalResponseTooLargeError):
                _run_get_rows([_login_response(), oversized], "projects")

    def test_slow_drip_body_aborts_on_total_deadline(self):
        # requests' timeout is an idle read timeout: a host that trickles bytes under the size
        # cap without ever idling long enough to trip it would otherwise hold the worker until
        # the activity's week-long timeout. The total-transfer deadline must abort it. Draining
        # via single reads (read1) means the deadline is checked before every read, so a host
        # dripping one byte per read can't stall inside a single read to dodge it. A monotonic
        # clock that advances one second per read crosses the (patched) 1s deadline within the
        # loop regardless of any monotonic() calls tenacity makes around it.
        response = mock.MagicMock(spec=requests.Response)
        response.raw = mock.MagicMock()
        response.raw.read1.side_effect = [b"x", b"y", b"z", b""]
        clock = itertools.count()
        with (
            mock.patch.object(infisical_module, "MAX_RESPONSE_SECONDS", 1),
            mock.patch.object(infisical_module.time, "monotonic", lambda: float(next(clock))),
        ):
            with pytest.raises(InfisicalResponseTooLargeError):
                infisical_module._read_capped_body(response)
        response.close.assert_called_once()

    def test_watchdog_shuts_socket_down_when_read_blocks_past_deadline(self):
        # read1 keeps the deadline enforceable between reads, but a chunked body falls through
        # to readline() while parsing the chunk-size line, which loops until CRLF — a host
        # dripping an unterminated size line stays inside one read past the deadline, so the
        # between-reads check never fires. The socket-level watchdog must shut the connection
        # down to force that read to return and abort. Firing the timer synchronously simulates
        # the deadline elapsing while a read is in flight.
        response = mock.MagicMock()

        class _ImmediateTimer:
            def __init__(self, interval, function, args=(), kwargs=None):
                self._function = function
                self._args = args

            def start(self):
                self._function(*self._args)

            def cancel(self):
                pass

        with mock.patch.object(infisical_module.threading, "Timer", _ImmediateTimer):
            with pytest.raises(InfisicalResponseTooLargeError):
                infisical_module._read_capped_body(response)
        response.raw._connection.sock.shutdown.assert_called_once()
        response.close.assert_called()

    def test_pagination_stops_at_max_pages(self):
        # A host that always returns a full page would loop forever without the page cap.
        identities_config = INFISICAL_ENDPOINTS["identities"]
        full1 = _response(json_data={"identityMemberships": [{"id": "a"}]})
        full2 = _response(json_data={"identityMemberships": [{"id": "b"}]})
        with (
            mock.patch.object(identities_config, "page_limit", 1),
            mock.patch.object(infisical_module, "MAX_PAGES", 2),
        ):
            rows, session, _manager = _run_get_rows([_login_response(), full1, full2], "identities")

        assert [r["id"] for r in rows] == ["a", "b"]
        assert len(_get_urls(session)) == 2


class TestValidateCredentials:
    def _run(self, responses: list[Any], schema_name: Optional[str] = None, **kwargs: Any):
        session = mock.MagicMock()
        session.request.side_effect = responses
        with (
            mock.patch.object(infisical_module, "make_tracked_session", return_value=session),
            mock.patch.object(infisical_module, "_is_host_safe", return_value=(True, None)),
        ):
            return (
                validate_credentials(
                    kwargs.pop("base_url", "https://app.infisical.com"),
                    "cid",
                    "csecret",
                    kwargs.pop("organization_id", "org-123"),
                    schema_name,
                    team_id=kwargs.pop("team_id", 1),
                ),
                session,
            )

    def test_login_success_at_source_create(self):
        result, session = self._run([_login_response()])
        assert result == (True, None)
        # Only the login probe — per-endpoint permissions are granted separately.
        assert session.request.call_count == 1

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    def test_login_rejection_is_invalid_credentials(self, status_code):
        result, _session = self._run([_response(status_code=status_code)])
        assert result == (False, INVALID_CREDENTIALS_ERROR)

    def test_scoped_probe_success(self):
        result, session = self._run(
            [_login_response(), _response(json_data={"auditLogs": []})], schema_name="audit_logs"
        )
        assert result == (True, None)
        assert "/api/v1/organization/audit-logs" in _get_urls(session)[0]

    def test_scoped_probe_403_names_the_table(self):
        result, _session = self._run([_login_response(), _response(status_code=403)], schema_name="audit_logs")
        valid, message = result
        assert valid is False
        assert "audit_logs" in (message or "")

    def test_invalid_base_url_short_circuits(self):
        result, session = self._run([], base_url="not a url!")
        assert result == (False, "Invalid Infisical base URL")
        session.request.assert_not_called()

    def test_invalid_organization_id_short_circuits(self):
        result, session = self._run([], organization_id="../../etc/passwd")
        assert result == (False, "Invalid Infisical organization ID")
        session.request.assert_not_called()

    def test_blocks_unsafe_host(self):
        session = mock.MagicMock()
        with (
            mock.patch.object(infisical_module, "make_tracked_session", return_value=session),
            mock.patch.object(infisical_module, "_is_host_safe", return_value=(False, "internal address")),
        ):
            result = validate_credentials("https://10.0.0.1", "cid", "csecret", "org-123", None, team_id=99)
        assert result == (False, "internal address")
        session.request.assert_not_called()

    def test_redirecting_host_is_rejected(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        result, _session = self._run([_response(status_code=302)])
        assert result == (False, infisical_module.HOST_NOT_ALLOWED_ERROR)

    def test_request_exception_returns_failure(self):
        result, _session = self._run([requests.exceptions.RequestException("boom")])
        valid, message = result
        assert valid is False
        assert "boom" in (message or "")


class TestInfisicalSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, sort_mode, partition_key",
        [
            ("audit_logs", "desc", "createdAt"),
            ("projects", "asc", None),
            ("identities", "asc", None),
            ("organization_memberships", "asc", None),
            ("project_memberships", "asc", None),
        ],
    )
    def test_response_shape(self, endpoint, sort_mode, partition_key):
        response = infisical_source(
            base_url="https://app.infisical.com",
            client_id="cid",
            client_secret="csecret",
            organization_id="org-123",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestRetryAfter:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        state = mock.MagicMock()
        state.outcome.exception.return_value = infisical_module.InfisicalRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0


class TestAuthErrors:
    def test_login_failure_raises_auth_error_from_get_rows(self):
        with pytest.raises(InfisicalAuthError):
            _run_get_rows([_response(status_code=401)], "projects")
