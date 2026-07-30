import time
import socket
import threading
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit import gerrit as gerrit_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.gerrit import (
    HOST_NOT_ALLOWED_ERROR,
    GerritResumeConfig,
    build_changes_query,
    format_after_value,
    gerrit_source,
    get_rows,
    normalize_host,
    parse_gerrit_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.settings import GERRIT_ENDPOINTS


def _response(*, status_code: int = 200, text: str = "", is_redirect: bool = False) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.text = text
    response.encoding = "utf-8"
    response.headers = {}
    # The source reads bodies with stream=True via response.iter_content; hand back the body in one
    # chunk (empty bodies yield nothing). A fresh iterator per call mirrors requests' behaviour.
    body = text.encode("utf-8")
    response.iter_content.side_effect = lambda chunk_size=None: iter([body] if body else [])
    # Responses are used as context managers (with session.get(...) as response).
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class _FakeResumeManager(ResumableSourceManager[GerritResumeConfig]):
    # In-memory stand-in — deliberately doesn't call super().__init__, so no Redis is touched.
    def __init__(self, state: Optional[GerritResumeConfig] = None):
        self._state = state
        self.saved: list[GerritResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[GerritResumeConfig]:
        return self._state

    def save_state(self, state: GerritResumeConfig) -> None:
        self.saved.append(state)


def _start_drip_server(byte_interval: float) -> int:
    """Serve a body one byte at a time, forever, on a loopback port. Returns the port.

    Models a host that trickles data just under the socket read timeout to keep a body read alive
    indefinitely. Threads are daemons and the socket is released once the client hangs up.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def _serve() -> None:
        try:
            conn, _ = server.accept()
            conn.recv(65536)  # consume the request line/headers
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\n")
            while True:
                conn.sendall(b"x")
                time.sleep(byte_interval)
        except OSError:
            pass
        finally:
            server.close()

    threading.Thread(target=_serve, name="drip-server", daemon=True).start()
    return port


def _patch_session(responses: list[mock.MagicMock]) -> tuple[mock.MagicMock, Any]:
    session = mock.MagicMock()
    session.get.side_effect = responses
    patcher = mock.patch.object(gerrit_module, "make_tracked_session", return_value=session)
    return session, patcher


def _get_all_rows(endpoint: str, session_responses: list[mock.MagicMock], **kwargs: Any) -> list[list[dict[str, Any]]]:
    session, session_patcher = _patch_session(session_responses)
    manager = kwargs.pop("manager", _FakeResumeManager())
    with (
        session_patcher,
        mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
    ):
        batches = list(
            get_rows(
                host="https://gerrit.example.com",
                username=kwargs.pop("username", "reviewbot"),
                http_password=kwargs.pop("http_password", "secret"),
                endpoint=endpoint,
                team_id=1,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches


class TestParseGerritResponse:
    @pytest.mark.parametrize(
        "text, expected",
        [
            (')]}\'\n[{"id": 1}]', [{"id": 1}]),
            (")]}'[]", []),
            ('[{"id": 1}]', [{"id": 1}]),  # some proxies strip the prefix already
            ('  )]}\'\n{"a": 1}', {"a": 1}),
        ],
    )
    def test_strips_xssi_prefix(self, text, expected):
        assert parse_gerrit_response(text) == expected


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://gerrit.example.com", "https://gerrit.example.com"),
            ("gerrit.example.com", "https://gerrit.example.com"),
            ("https://gerrit.example.com/", "https://gerrit.example.com"),
            # A trailing /a (the authenticated prefix we add ourselves) is stripped, but a
            # genuine context path (self-hosted Gerrit mounted under /r) is preserved.
            ("https://gerrit.example.com/a", "https://gerrit.example.com"),
            ("https://example.com/r/", "https://example.com/r"),
            ("https://example.com/r/a", "https://example.com/r"),
            ("  gerrit.example.com  ", "https://gerrit.example.com"),
            # Plaintext HTTP to a remote host is upgraded to HTTPS so credentials aren't sent in the clear.
            ("http://gerrit.example.com", "https://gerrit.example.com"),
            ("http://localhost:8080", "http://localhost:8080"),
            ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestChangesQuery:
    def test_no_watermark_matches_all_statuses(self):
        assert build_changes_query(None) == "status:open OR status:closed"

    def test_watermark_appends_after_operator(self):
        query = build_changes_query(datetime(2026, 7, 15, 16, 15, 24))
        assert query == '(status:open OR status:closed) after:"2026-07-15 16:15:24"'

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 7, 15, 16, 15, 24), "2026-07-15 16:15:24"),
            # Aware datetimes are converted to UTC — Gerrit timestamps are UTC.
            (datetime(2026, 7, 15, 18, 15, 24, tzinfo=timezone(timedelta(hours=2))), "2026-07-15 16:15:24"),
            (datetime(2026, 7, 15, 16, 15, 24, tzinfo=UTC), "2026-07-15 16:15:24"),
            (datetime(2026, 7, 15).date(), "2026-07-15 00:00:00"),
            ("2026-07-15 16:15:24.000000000", "2026-07-15 16:15:24.000000000"),
        ],
    )
    def test_format_after_value(self, value, expected):
        assert format_after_value(value) == expected


class TestGetRows:
    def test_paginates_with_offset_until_more_flag_absent(self):
        page_1 = ")]}'\n" + '[{"id": "p~1", "updated": "t1"}, {"id": "p~2", "updated": "t2", "_more_changes": true}]'
        page_2 = ")]}'\n" + '[{"id": "p~3", "updated": "t3"}]'
        session, session_patcher = _patch_session([_response(text=page_1), _response(text=page_2)])
        manager = _FakeResumeManager()

        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
        ):
            batches = list(
                get_rows(
                    host="https://gerrit.example.com",
                    username="reviewbot",
                    http_password="secret",
                    endpoint="changes",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        # The _more_changes marker is pagination metadata, not a row column.
        assert batches == [
            [{"id": "p~1", "updated": "t1"}, {"id": "p~2", "updated": "t2"}],
            [{"id": "p~3", "updated": "t3"}],
        ]

        first_url = session.get.call_args_list[0].args[0]
        second_url = session.get.call_args_list[1].args[0]
        # Authenticated requests go through the /a/ prefix; page 2 skips the rows already fetched.
        assert "/a/changes/" in first_url
        assert "S=" not in first_url
        assert "S=2" in second_url

        # Resume state is saved after yielding a page, and only while more pages remain.
        assert [s.offset for s in manager.saved] == [2]

    def test_resumes_from_saved_offset(self):
        page = ")]}'\n" + '[{"id": "p~51"}]'
        session, session_patcher = _patch_session([_response(text=page)])
        manager = _FakeResumeManager(state=GerritResumeConfig(offset=50))

        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
        ):
            list(
                get_rows(
                    host="https://gerrit.example.com",
                    username="reviewbot",
                    http_password="secret",
                    endpoint="changes",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert "S=50" in session.get.call_args_list[0].args[0]

    def test_incremental_sync_sends_after_filter(self):
        session, session_patcher = _patch_session([_response(text=")]}'\n[]")])

        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
        ):
            list(
                get_rows(
                    host="https://gerrit.example.com",
                    username="reviewbot",
                    http_password="secret",
                    endpoint="changes",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeResumeManager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 7, 15, 16, 15, 24),
                )
            )

        url = session.get.call_args_list[0].args[0]
        assert "after%3A%222026-07-15+16%3A15%3A24%22" in url

    def test_map_endpoint_rows_carry_name_from_key(self):
        body = (
            ")]}'\n"
            '{"Core-Plugins": {"id": "Core-Plugins", "state": "ACTIVE"},'
            ' "gerrit": {"id": "gerrit", "name": "gerrit", "state": "ACTIVE"}}'
        )
        batches = _get_all_rows("projects", [_response(text=body)])

        assert batches == [
            [
                {"id": "Core-Plugins", "state": "ACTIVE", "name": "Core-Plugins"},
                {"id": "gerrit", "name": "gerrit", "state": "ACTIVE"},
            ]
        ]

    def test_anonymous_requests_skip_the_auth_prefix(self):
        session, session_patcher = _patch_session([_response(text=")]}'\n[]")])

        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
        ):
            list(
                get_rows(
                    host="https://gerrit.example.com",
                    username=None,
                    http_password=None,
                    endpoint="changes",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeResumeManager(),
                )
            )

        url = session.get.call_args_list[0].args[0]
        assert "/a/" not in url
        assert "https://gerrit.example.com/changes/" in url

    def test_oversized_response_body_is_rejected(self):
        body = ")]}'\n" + "[" + ",".join(f'{{"id": "p~{i}"}}' for i in range(50)) + "]"
        with (
            mock.patch.object(gerrit_module, "MAX_RESPONSE_BYTES", 8),
            pytest.raises(gerrit_module.GerritResponseTooLargeError),
        ):
            _get_all_rows("changes", [_response(text=body)])

    def test_slow_drip_body_returns_at_the_download_deadline(self):
        # A hostile host can drip one byte just under the socket read timeout, which keeps a single
        # urllib3 body read parked in recv indefinitely — the per-recv timeout resets on every byte,
        # so it never bounds total download time, and close() from a timer does not cancel a parked
        # read. The drain must be abandoned at MAX_DOWNLOAD_SECONDS so a shared sync worker is never
        # held open by such a host. Exercised against a real loopback server because the regression
        # lives in the socket/urllib3 read path, which a mocked iter_content can't reproduce.
        port = _start_drip_server(byte_interval=0.05)  # never finishes within the deadline
        session = requests.Session()
        response = session.get(f"http://127.0.0.1:{port}", stream=True, timeout=5)

        start = time.monotonic()
        with (
            mock.patch.object(gerrit_module, "MAX_DOWNLOAD_SECONDS", 0.5),
            pytest.raises(gerrit_module.GerritResponseTooLargeError),
        ):
            gerrit_module._read_capped_text(response)
        # Returned at the deadline rather than blocking on the drip (which would run for minutes).
        assert time.monotonic() - start < 3.0

    def test_unsafe_host_is_rejected_before_any_request(self):
        session, session_patcher = _patch_session([])

        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(False, "internal IP")),
            pytest.raises(gerrit_module.GerritHostNotAllowedError),
        ):
            list(
                get_rows(
                    host="https://internal.example.com",
                    username=None,
                    http_password=None,
                    endpoint="changes",
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeResumeManager(),
                )
            )

        session.get.assert_not_called()


class TestGerritSourceResponse:
    def test_changes_response_shape(self):
        response = gerrit_source(
            host="https://gerrit.example.com",
            username="reviewbot",
            http_password="secret",
            endpoint="changes",
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeResumeManager(),
        )

        assert response.name == "changes"
        assert response.primary_keys == ["id"]
        # Gerrit returns changes newest-first, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"

    @pytest.mark.parametrize("endpoint", ["accounts", "projects", "groups"])
    def test_dimension_endpoints_are_unpartitioned(self, endpoint):
        response = gerrit_source(
            host="https://gerrit.example.com",
            username=None,
            http_password=None,
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == GERRIT_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestValidateCredentials:
    def _validate(self, responses: list[mock.MagicMock], **kwargs: Any) -> tuple[bool, str | None]:
        session, session_patcher = _patch_session(responses)
        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(True, None)),
        ):
            result = validate_credentials(
                host=kwargs.pop("host", "https://gerrit.example.com"),
                username=kwargs.pop("username", "reviewbot"),
                http_password=kwargs.pop("http_password", "secret"),
                team_id=kwargs.pop("team_id", 1),
                **kwargs,
            )
        self.session = session
        return result

    def test_valid_credentials_probe_accounts_self(self):
        valid, error = self._validate([_response(text=')]}\'\n{"_account_id": 1}')])
        assert (valid, error) == (True, None)
        assert "/a/accounts/self" in self.session.get.call_args.args[0]

    def test_anonymous_probe_uses_server_version(self):
        valid, error = self._validate(
            [_response(text=')]}\'\n"3.10.0"')],
            username=None,
            http_password=None,
        )
        assert (valid, error) == (True, None)
        assert self.session.get.call_args.args[0] == "https://gerrit.example.com/config/server/version"

    def test_401_is_invalid(self):
        valid, error = self._validate([_response(status_code=401, text="Unauthorized")])
        assert valid is False
        assert error is not None and "HTTP password" in error

    def test_403_passes_at_source_create_but_fails_per_schema(self):
        assert self._validate([_response(status_code=403)])[0] is True
        valid, error = self._validate([_response(status_code=403)], schema_name="groups")
        assert valid is False
        assert error is not None and "permission" in error

    def test_schema_probe_hits_the_endpoint(self):
        self._validate([_response(text=")]}'\n{}")], schema_name="groups")
        assert "/a/groups/?" in self.session.get.call_args.args[0]

    def test_redirect_is_rejected(self):
        valid, error = self._validate([_response(status_code=302, is_redirect=True)])
        assert (valid, error) == (False, HOST_NOT_ALLOWED_ERROR)

    def test_non_json_200_is_rejected(self):
        valid, error = self._validate([_response(text="<html>a login page</html>")])
        assert valid is False
        assert error is not None and "valid API response" in error

    def test_oversized_response_body_is_rejected(self):
        with mock.patch.object(gerrit_module, "MAX_RESPONSE_BYTES", 8):
            valid, error = self._validate([_response(text=')]}\'\n{"_account_id": 1, "padding": "xxxxxxxxxx"}')])
        assert valid is False
        assert error is not None and "large" in error

    def test_username_without_password_is_rejected_without_a_request(self):
        valid, error = self._validate([], http_password=None)
        assert valid is False
        assert error is not None and "both" in error
        self.session.get.assert_not_called()

    def test_unsafe_host_is_rejected(self):
        session, session_patcher = _patch_session([])
        with (
            session_patcher,
            mock.patch.object(gerrit_module, "_is_host_safe", return_value=(False, "internal IP")),
        ):
            valid, error = validate_credentials(
                host="https://internal.example.com", username=None, http_password=None, team_id=1
            )
        assert (valid, error) == (False, "internal IP")
        session.get.assert_not_called()
