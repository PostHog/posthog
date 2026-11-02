import time
import socket
import itertools
import threading
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    FakeNetwork,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.infisical import (
    InfisicalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical import infisical as infisical_module
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.infisical import (
    INVALID_CREDENTIALS_ERROR,
    InfisicalAuthError,
    InfisicalFanOutBudgetExceededError,
    InfisicalPaginationBudgetExceededError,
    InfisicalResponseTooLargeError,
    InfisicalResumeConfig,
    _format_incremental_value,
    _get_audit_log_rows,
    _get_fan_out_rows,
    _get_offset_paginated_rows,
    _parse_retry_after,
    _retry_wait,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.settings import INFISICAL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source import InfisicalSource

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


def _driver() -> SourceDriver:
    return SourceDriver(
        InfisicalSource(),
        InfisicalSourceConfig(
            base_url="https://app.infisical.com",
            organization_id="org-123",
            client_id="cid",
            client_secret="csecret",
        ),
    )


def _scripted_login_response() -> ScriptedResponse:
    return ScriptedResponse(json=LOGIN_JSON)


class TestNormalizeBaseUrl:
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
        page1 = ScriptedResponse(json={"auditLogs": [{"id": i, "orgId": "org-123"} for i in ("3", "2", "1")]})
        page2 = ScriptedResponse(json={"auditLogs": [{"id": "0", "orgId": "org-123"}]})
        with mock.patch.object(audit_config, "page_limit", 3):
            result = _driver().run(
                "audit_logs",
                [_scripted_login_response(), page1, page2],
                incremental_field="createdAt",
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )

        assert [r["id"] for r in result.rows] == ["3", "2", "1", "0"]

        first, second = result.requests[1:]
        assert first.param("startDate") == "2024-01-01T00:00:00.000Z"
        assert first.param("offset") == "0"
        assert second.param("offset") == "3"
        # endDate is pinned at sync start so offset pagination stays stable while new logs arrive.
        assert first.param("endDate") == second.param("endDate")
        # A short page terminates pagination.
        assert len(result.requests) == 3

        assert [state.offset for state in result.saved_states] == [3, 4]

    def test_resumes_saved_window_and_offset(self):
        resume = InfisicalResumeConfig(
            offset=7, window_start="2024-01-01T00:00:00.000Z", window_end="2024-06-01T00:00:00.000Z"
        )
        page = ScriptedResponse(json={"auditLogs": [{"id": "1", "orgId": "org-123"}]})
        result = _driver().run("audit_logs", [_scripted_login_response(), page], resume_state=resume)

        request = result.requests[1]
        assert request.param("offset") == "7"
        assert request.param("startDate") == "2024-01-01T00:00:00.000Z"
        assert request.param("endDate") == "2024-06-01T00:00:00.000Z"

    def test_empty_first_page_yields_nothing(self):
        page = ScriptedResponse(json={"auditLogs": []})
        result = _driver().run("audit_logs", [_scripted_login_response(), page])

        assert result.rows == []
        assert result.saved_states == []


class TestOffsetPaginatedRows:
    def test_identities_paginates_with_stable_sort(self):
        identities_config = INFISICAL_ENDPOINTS["identities"]
        page1 = ScriptedResponse(json={"identityMemberships": [{"id": "a"}, {"id": "b"}]})
        page2 = ScriptedResponse(json={"identityMemberships": [{"id": "c"}]})
        with mock.patch.object(identities_config, "page_limit", 2):
            result = _driver().run("identities", [_scripted_login_response(), page1, page2])

        assert [r["id"] for r in result.rows] == ["a", "b", "c"]

        assert result.paths[1:] == ["/api/v2/organizations/org-123/identity-memberships"] * 2
        first, second = result.requests[1:]
        assert first.param("orderBy") == "name"
        assert first.param("orderDirection") == "asc"
        assert first.param("offset") == "0"
        assert second.param("offset") == "2"
        assert [state.offset for state in result.saved_states] == [2, 3]


class TestProjectMembershipsFanOut:
    def test_fans_out_over_projects_and_skips_forbidden(self):
        projects = ScriptedResponse(
            json={
                "projects": [
                    {"id": "p1", "orgId": "org-123"},
                    {"id": "p2", "orgId": "org-123"},
                    {"id": "p3", "orgId": "org-123"},
                ]
            }
        )
        memberships_p1 = ScriptedResponse(json={"memberships": [{"id": "m1", "projectId": "p1"}]})
        memberships_p2 = ScriptedResponse(status=403)
        memberships_p3 = ScriptedResponse(json={"memberships": [{"id": "m2", "projectId": "p3"}]})
        result = _driver().run(
            "project_memberships",
            [_scripted_login_response(), projects, memberships_p1, memberships_p2, memberships_p3],
        )

        # The 403 project is skipped (per-project grants), the rest still sync.
        assert [r["id"] for r in result.rows] == ["m1", "m2"]
        assert result.paths[1:] == [
            "/api/v1/projects",
            "/api/v1/projects/p1/memberships",
            "/api/v1/projects/p2/memberships",
            "/api/v1/projects/p3/memberships",
        ]

    @pytest.mark.parametrize("status_code", [400, 403])
    def test_fails_the_sync_when_no_project_is_readable(self, status_code):
        # A 403 on every project means the identity lacks the permission outright, so an empty
        # full refresh must not be reported as a success.
        projects = ScriptedResponse(json={"projects": [{"id": "p1", "orgId": "org-123"}]})
        error = ScriptedResponse(status=status_code)
        result = _driver().run("project_memberships", [_scripted_login_response(), projects, error])
        assert isinstance(result.raised, requests.HTTPError)

    def test_fan_out_is_capped(self):
        # base_url is customer-controlled: a host returning far more projects than any real org
        # (still under the byte cap) would fan one sync out into a request per project and hold
        # the worker. The fan-out must stop at MAX_FAN_OUT_PARENTS.
        projects = ScriptedResponse(json={"projects": [{"id": f"p{i}", "orgId": "org-123"} for i in range(3)]})
        membership = ScriptedResponse(json={"memberships": [{"id": "m1", "projectId": "p0"}]})
        with mock.patch.object(infisical_module, "MAX_FAN_OUT_PARENTS", 2):
            result = _driver().run(
                "project_memberships", [_scripted_login_response(), projects, membership, membership]
            )

        # Only the first 2 of the 3 projects are fetched (1 project list + 2 membership calls).
        membership_paths = [p for p in result.paths if "memberships" in p]
        assert membership_paths == ["/api/v1/projects/p0/memberships", "/api/v1/projects/p1/memberships"]

    def test_fan_out_aborts_when_time_budget_exhausted(self):
        # The project-count cap doesn't bound how long each membership response takes: a hostile
        # host can stay under the cap yet drain every response's full deadline, holding the worker
        # for weeks. The wall-clock fan-out budget must abort the sync — not truncate — once spent.
        config = INFISICAL_ENDPOINTS["project_memberships"]
        client = mock.MagicMock()
        projects = _response(json_data={"projects": [{"id": f"p{i}", "orgId": "org-123"} for i in range(5)]})
        membership = _response(json_data={"memberships": [{"id": "m", "projectId": "p"}]})
        client.get.side_effect = [projects, *([membership] * 5)]

        # A clock that jumps one per-response deadline on every check, so a two-response budget is
        # spent after the first couple of projects — simulating each response draining its deadline.
        clock = itertools.count(0, infisical_module.MAX_RESPONSE_SECONDS)
        with (
            mock.patch.object(infisical_module, "MAX_FAN_OUT_SECONDS", infisical_module.MAX_RESPONSE_SECONDS * 2),
            mock.patch.object(infisical_module.time, "monotonic", lambda: next(clock)),
            pytest.raises(InfisicalFanOutBudgetExceededError),
        ):
            list(_get_fan_out_rows(client, config, "org-123", mock.MagicMock()))

        # Aborted mid-fan-out: not every project was fetched.
        membership_calls = [c for c in client.get.call_args_list if "memberships" in c.args[0]]
        assert 0 < len(membership_calls) < 5


class TestGroupMembersFanOut:
    def test_paginates_each_group_and_stamps_group_id(self):
        groups = ScriptedResponse(json=[{"id": "g1", "orgId": "org-123"}, {"id": "g2", "orgId": "other-org"}])
        page1 = ScriptedResponse(
            json={"members": [{"id": "u1", "type": "user"}, {"id": "i1", "type": "machineIdentity"}]}
        )
        page2 = ScriptedResponse(json={"members": [{"id": "u2", "type": "user"}]})
        with mock.patch.object(INFISICAL_ENDPOINTS["group_members"], "page_limit", 2):
            result = _driver().run("group_members", [_scripted_login_response(), groups, page1, page2])

        # Member rows don't carry their group, so without the stamp the composite key collapses
        # across groups.
        assert [(r["groupId"], r["id"]) for r in result.rows] == [("g1", "u1"), ("g1", "i1"), ("g1", "u2")]
        # The other org's group is never fetched.
        assert result.paths[1:] == ["/api/v1/groups", *["/api/v1/groups/g1/members"] * 2]
        assert result.params("offset")[2:] == ["0", "2"]


class TestProjectTypeScopedFanOut:
    @pytest.mark.parametrize(
        "endpoint, project_type, path, data_key",
        [
            ("secret_scanning_findings", "secret-scanning", "/api/v2/secret-scanning/findings", "findings"),
            ("secret_syncs", "secret-manager", "/api/v1/secret-syncs", "secretSyncs"),
        ],
    )
    def test_only_matching_projects_are_queried_by_project_id(self, endpoint, project_type, path, data_key):
        # These endpoints reject other project types with a 400, which would fail the sync.
        projects = ScriptedResponse(
            json={
                "projects": [
                    {"id": "p1", "orgId": "org-123", "type": "cert-manager"},
                    {"id": "p2", "orgId": "org-123", "type": project_type},
                ]
            }
        )
        children = ScriptedResponse(json={data_key: [{"id": "c1", "projectId": "p2"}]})
        result = _driver().run(endpoint, [_scripted_login_response(), projects, children])

        assert [r["id"] for r in result.rows] == ["c1"]
        assert result.paths[2] == path
        assert result.queries[2] == {"projectId": ("p2",)}


class TestProjectEnvironmentsFanOut:
    def test_fetches_each_embedded_environment_of_the_org_projects(self):
        projects = ScriptedResponse(
            json={
                "projects": [
                    {"id": "p1", "orgId": "org-123", "environments": [{"id": "e1"}, {"id": "e2"}]},
                    {"id": "p2", "orgId": "other-org", "environments": [{"id": "e3"}]},
                    {"id": "p3", "orgId": "org-123", "environments": []},
                ]
            }
        )
        env1 = ScriptedResponse(json={"environment": {"id": "e1", "slug": "dev", "projectId": "p1"}})
        env2 = ScriptedResponse(status=404)
        result = _driver().run("project_environments", [_scripted_login_response(), projects, env1, env2])

        # A single-object body becomes one row; an environment deleted mid-sync is skipped.
        assert result.rows == [{"id": "e1", "slug": "dev", "projectId": "p1"}]
        assert result.paths[1:] == [
            "/api/v1/projects",
            "/api/v1/projects/p1/environments/e1",
            "/api/v1/projects/p1/environments/e2",
        ]


class TestOrgScoping:
    @pytest.mark.parametrize(
        "endpoint, body",
        [
            ("organization_roles", {"roles": [{"id": "r1", "orgId": "org-123"}, {"id": "r2", "orgId": "other-org"}]}),
            ("groups", [{"id": "r1", "orgId": "org-123"}, {"id": "r2", "orgId": "other-org"}]),
        ],
    )
    def test_token_scoped_tables_exclude_other_orgs(self, endpoint, body):
        result = _driver().run(endpoint, [_scripted_login_response(), ScriptedResponse(json=body)])
        assert [r["id"] for r in result.rows] == ["r1"]


class TestTokenHandling:
    def test_relogins_once_when_token_rejected_mid_sync(self):
        rejected = ScriptedResponse(status=401)
        page = ScriptedResponse(json={"projects": [{"id": "1", "orgId": "org-123"}]})
        result = _driver().run("projects", [_scripted_login_response(), rejected, _scripted_login_response(), page])

        assert [r["id"] for r in result.rows] == ["1"]
        logins = [request for request in result.requests if request.method == "POST"]
        assert len(logins) == 2

    def test_requests_never_follow_redirects(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/api/v1/projects"})
        result = _driver().run("projects", [_scripted_login_response(), redirect])

        assert isinstance(result.raised, infisical_module.InfisicalHostNotAllowedError)
        assert len(result.requests) == 2
        assert all(request.url.startswith("https://app.infisical.com") for request in result.requests)

    def test_rejects_unsafe_host_before_any_request(self):
        with mock.patch.object(infisical_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("projects", [])

        assert isinstance(result.raised, infisical_module.InfisicalHostNotAllowedError)
        assert result.requests == []


class TestResponseLimits:
    def test_oversized_response_is_rejected(self):
        # base_url is customer-controlled, so an unbounded body must abort rather than buffer
        # into memory and exhaust the worker.
        oversized = ScriptedResponse(body=b"x" * 2048)
        with mock.patch.object(infisical_module, "MAX_RESPONSE_BYTES", 1024):
            result = _driver().run("projects", [_scripted_login_response(), oversized])
        assert isinstance(result.raised, InfisicalResponseTooLargeError)

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

    def test_chunked_size_line_drip_aborts_as_deadline_error(self):
        # End-to-end over a real socket: a chunked host drips an unterminated chunk-size line,
        # so read1 blocks inside the stdlib readline() past the deadline. The watchdog shutting
        # the socket down unblocks that read, and whatever error the interrupted/closed read
        # raises must surface as InfisicalResponseTooLargeError — not a raw socket/attribute
        # error. The synchronous-timer test above can't reach this: it fires before any read,
        # so it never exercises the interrupted-read translation path. Aborting near the
        # (patched) deadline rather than when the drip ends proves the watchdog fired.
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        stop = threading.Event()

        def drip() -> None:
            conn, _ = server.accept()
            conn.recv(65536)
            conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            # Digits with no CRLF, so readline never completes the chunk-size line. Bounded so a
            # broken watchdog fails the timing assertion instead of hanging the suite.
            for _ in range(250):
                if stop.is_set():
                    break
                try:
                    conn.sendall(b"1")
                except OSError:
                    break
                stop.wait(0.02)
            conn.close()

        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        try:
            response = requests.get(f"http://127.0.0.1:{port}/", stream=True, timeout=30)
            started = time.monotonic()
            with mock.patch.object(infisical_module, "MAX_RESPONSE_SECONDS", 1.0):
                with pytest.raises(InfisicalResponseTooLargeError):
                    infisical_module._read_capped_body(response)
            assert time.monotonic() - started < 3.0
        finally:
            stop.set()
            server.close()
            thread.join(timeout=5)

    def test_pagination_stops_at_max_pages(self):
        # A host that always returns a full page would loop forever without the page cap.
        identities_config = INFISICAL_ENDPOINTS["identities"]
        full1 = ScriptedResponse(json={"identityMemberships": [{"id": "a"}]})
        full2 = ScriptedResponse(json={"identityMemberships": [{"id": "b"}]})
        with (
            mock.patch.object(identities_config, "page_limit", 1),
            mock.patch.object(infisical_module, "MAX_PAGES", 2),
        ):
            result = _driver().run("identities", [_scripted_login_response(), full1, full2])

        assert [r["id"] for r in result.rows] == ["a", "b"]
        assert len(result.requests) == 3

    @pytest.mark.parametrize(
        "endpoint, run_loop",
        [
            (
                "identities",
                lambda client, config, manager: _get_offset_paginated_rows(
                    client, config, "org-123", manager, mock.MagicMock()
                ),
            ),
            (
                "audit_logs",
                lambda client, config, manager: _get_audit_log_rows(
                    client, config, "org-123", mock.MagicMock(), manager, False, None
                ),
            ),
        ],
    )
    def test_pagination_aborts_when_time_budget_exhausted(self, endpoint, run_loop):
        # MAX_PAGES bounds page count, not per-page time: a hostile host can return a full page that
        # drains its whole response deadline on every one of MAX_PAGES pages, holding the worker for
        # ~a year. The wall-clock pagination budget must abort the sync — not silently truncate —
        # once spent.
        config = INFISICAL_ENDPOINTS[endpoint]
        client = mock.MagicMock()
        full_page = _response(json_data={config.data_key: [{"id": f"r{i}"} for i in range(config.page_limit)]})
        client.get.return_value = full_page
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        # A clock that jumps one per-response deadline on every check, so a two-response budget is
        # spent after the first couple of pages — simulating each page draining its full deadline.
        clock = itertools.count(0, infisical_module.MAX_RESPONSE_SECONDS)
        with (
            mock.patch.object(infisical_module, "MAX_PAGINATION_SECONDS", infisical_module.MAX_RESPONSE_SECONDS * 2),
            mock.patch.object(infisical_module.time, "monotonic", lambda: next(clock)),
            pytest.raises(InfisicalPaginationBudgetExceededError),
        ):
            list(run_loop(client, config, manager))

        # Aborted mid-pagination rather than running all the way to MAX_PAGES.
        assert 0 < client.get.call_count < infisical_module.MAX_PAGES


class TestValidateCredentials:
    def _run(
        self, responses: Script, schema_name: Optional[str] = None, **kwargs: Any
    ) -> tuple[tuple[bool, str | None], FakeNetwork]:
        with scripted_network(responses) as network:
            result = validate_credentials(
                kwargs.pop("base_url", "https://app.infisical.com"),
                "cid",
                "csecret",
                kwargs.pop("organization_id", "org-123"),
                schema_name,
                team_id=kwargs.pop("team_id", 1),
            )
        return result, network

    def test_login_success_at_source_create(self):
        result, network = self._run([_scripted_login_response()])
        assert result == (True, None)
        # Only the login probe — per-endpoint permissions are granted separately.
        assert len(network.requests_log) == 1

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    def test_login_rejection_is_invalid_credentials(self, status_code):
        result, _network = self._run([ScriptedResponse(status=status_code)])
        assert result == (False, INVALID_CREDENTIALS_ERROR)

    @pytest.mark.parametrize(
        "schema_name, body, expected_path",
        [
            ("audit_logs", {"auditLogs": []}, "/api/v1/organization/audit-logs"),
            # Fan-out tables probe the parent list, never a path with unfilled placeholders.
            ("project_environments", {"projects": []}, "/api/v1/projects"),
        ],
    )
    def test_scoped_probe_success(self, schema_name, body, expected_path):
        result, network = self._run([_scripted_login_response(), ScriptedResponse(json=body)], schema_name=schema_name)
        assert result == (True, None)
        assert network.requests_log[1].path == expected_path

    def test_scoped_probe_403_names_the_table(self):
        result, _network = self._run(
            [_scripted_login_response(), ScriptedResponse(status=403)], schema_name="audit_logs"
        )
        valid, message = result
        assert valid is False
        assert "audit_logs" in (message or "")

    def test_invalid_base_url_short_circuits(self):
        result, network = self._run([], base_url="not a url!")
        assert result == (False, "Invalid Infisical base URL")
        assert network.requests_log == []

    def test_invalid_organization_id_short_circuits(self):
        result, network = self._run([], organization_id="../../etc/passwd")
        assert result == (False, "Invalid Infisical organization ID")
        assert network.requests_log == []

    def test_blocks_unsafe_host(self):
        with mock.patch.object(infisical_module, "_is_host_safe", return_value=(False, "internal address")):
            result, network = self._run([], base_url="https://10.0.0.1", team_id=99)
        assert result == (False, "internal address")
        assert network.requests_log == []

    def test_redirecting_host_is_rejected(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        result, _network = self._run(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"})]
        )
        assert result == (False, infisical_module.HOST_NOT_ALLOWED_ERROR)

    def test_request_exception_returns_failure(self):
        result, _network = self._run([requests.exceptions.RequestException("boom")])
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
        data_key = INFISICAL_ENDPOINTS[endpoint].data_key
        body = {data_key: []} if data_key is not None else []
        result = _driver().run(endpoint, [_scripted_login_response(), ScriptedResponse(json=body)])
        assert result.raised is None
        response = result.response
        assert response is not None
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
        result = _driver().run("projects", [ScriptedResponse(status=401)])
        assert isinstance(result.raised, InfisicalAuthError)
