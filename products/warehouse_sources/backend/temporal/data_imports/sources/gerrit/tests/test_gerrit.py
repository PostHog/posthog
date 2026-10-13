import time
import socket
import threading
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gerrit import GerritSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit import gerrit as gerrit_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.gerrit import (
    HOST_NOT_ALLOWED_ERROR,
    GerritResumeConfig,
    build_changes_query,
    format_after_value,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source import GerritSource


def _response(*, status_code: int = 200, text: str = "") -> ScriptedResponse:
    return ScriptedResponse(status=status_code, body=text.encode())


def _driver(config: GerritSourceConfig | None = None) -> SourceDriver:
    return SourceDriver(
        GerritSource(),
        config or GerritSourceConfig(host="https://gerrit.example.com", username="reviewbot", http_password="secret"),
    )


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
    def test_resumes_from_saved_offset(self):
        page = ")]}'\n" + '[{"id": "p~51"}]'
        result = _driver().run("changes", [_response(text=page)], resume_state=GerritResumeConfig(offset=50))

        assert result.raised is None
        assert result.requests[0].param("S") == "50"

    @pytest.mark.parametrize(
        "endpoint, parent_body, child_responses, expected_child_paths, expected_batches",
        [
            (
                "group_members",
                '{"Admins": {"id": "abc123"}, "ldap/eng": {"id": "ldap%3Acn%3Deng"}}',
                # External groups have no member list and answer 405.
                [_response(text=")]}'\n" + '[{"_account_id": 7, "name": "Ada"}]'), _response(status_code=405)],
                ["/a/groups/abc123/members/", "/a/groups/ldap%3Acn%3Deng/members/"],
                [[{"_account_id": 7, "name": "Ada", "group_uuid": "abc123"}]],
            ),
            (
                "project_branches",
                '{"plugins/replication": {"id": "plugins%2Freplication"}, "gerrit": {"id": "gerrit"}}',
                [
                    _response(text=")]}'\n" + '[{"ref": "refs/heads/main", "revision": "abc"}]'),
                    _response(text=")]}'\n" + '[{"ref": "refs/heads/stable", "revision": "def"}]'),
                ],
                ["/a/projects/plugins%2Freplication/branches/", "/a/projects/gerrit/branches/"],
                # One batch per parent, so a page of fan-out children is never buffered whole.
                [
                    [{"ref": "refs/heads/main", "revision": "abc", "project": "plugins/replication"}],
                    [{"ref": "refs/heads/stable", "revision": "def", "project": "gerrit"}],
                ],
            ),
            (
                "change_comments",
                '[{"id": "plugins%2Freplication~12", "_number": 12, "project": "plugins/replication",'
                ' "updated": "u12", "created": "c12"}, {"id": "gerrit~13", "_number": 13, "project": "gerrit"}]',
                # A change deleted between the listing and the comments request answers 404.
                [
                    _response(
                        text=")]}'\n" + '{"src/a.py": [{"id": "c1", "line": 3}, {"id": "c2", "in_reply_to": "c1"}],'
                        ' "/COMMIT_MSG": [{"id": "c3"}]}'
                    ),
                    _response(status_code=404),
                ],
                ["/a/changes/plugins%2Freplication~12/comments", "/a/changes/gerrit~13/comments"],
                [
                    [
                        {
                            "path": "src/a.py",
                            "id": "c1",
                            "line": 3,
                            "_change_number": 12,
                            "project": "plugins/replication",
                            "change_updated": "u12",
                            "change_created": "c12",
                        },
                        {
                            "path": "src/a.py",
                            "id": "c2",
                            "in_reply_to": "c1",
                            "_change_number": 12,
                            "project": "plugins/replication",
                            "change_updated": "u12",
                            "change_created": "c12",
                        },
                        {
                            "path": "/COMMIT_MSG",
                            "id": "c3",
                            "_change_number": 12,
                            "project": "plugins/replication",
                            "change_updated": "u12",
                            "change_created": "c12",
                        },
                    ],
                ],
            ),
        ],
    )
    def test_fanout_fetches_children_per_parent(
        self, endpoint, parent_body, child_responses, expected_child_paths, expected_batches
    ):
        result = _driver().run(endpoint, [_response(text=")]}'\n" + parent_body), *child_responses])

        assert result.raised is None
        assert result.urls[1:] == [f"https://gerrit.example.com{path}" for path in expected_child_paths]
        assert result.items == expected_batches

    def test_fanout_child_error_other_than_ignored_statuses_fails_the_sync(self):
        parent_body = ")]}'\n" + '{"gerrit": {"id": "gerrit"}}'
        result = _driver().run("project_branches", [_response(text=parent_body), _response(status_code=403)])

        assert isinstance(result.raised, requests.HTTPError)

    def test_change_files_flattens_current_revision_files(self):
        body = (
            ")]}'\n"
            '[{"id": "gerrit~12", "_number": 12, "project": "gerrit", "updated": "u", "created": "c",'
            ' "current_revision": "sha2", "revisions": {"sha2": {"_number": 2, "files": {'
            '"src/a.py": {"lines_inserted": 5, "lines_deleted": 1},'
            ' "img.png": {"binary": true, "status": "A"}}}}},'
            ' {"id": "gerrit~13", "_number": 13, "project": "gerrit", "current_revision": "sha9",'
            ' "revisions": {"sha9": {"_number": 1}}, "_more_changes": true}]'
        )
        page_2 = ")]}'\n[]"
        result = _driver().run("change_files", [_response(text=body), _response(text=page_2)])

        parent = {"_change_number": 12, "project": "gerrit", "change_updated": "u", "change_created": "c"}
        assert result.raised is None
        assert result.items == [
            [
                {
                    "lines_inserted": 5,
                    "lines_deleted": 1,
                    "path": "src/a.py",
                    "revision": "sha2",
                    "_revision_number": 2,
                    **parent,
                },
                {"binary": True, "status": "A", "path": "img.png", "revision": "sha2", "_revision_number": 2, **parent},
            ]
        ]
        assert result.requests[0].query["o"] == ("CURRENT_REVISION", "CURRENT_FILES")
        # The resume offset counts changes, not file rows, because `S` skips changes.
        assert result.requests[1].param("S") == "2"
        assert result.saved_states == [GerritResumeConfig(offset=2)]

    def test_oversized_response_body_is_rejected(self):
        body = ")]}'\n" + "[" + ",".join(f'{{"id": "p~{i}"}}' for i in range(50)) + "]"
        with mock.patch.object(gerrit_module, "MAX_RESPONSE_BYTES", 8):
            result = _driver().run("changes", [_response(text=body)])
        assert isinstance(result.raised, gerrit_module.GerritResponseTooLargeError)

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
        config = GerritSourceConfig(host="https://internal.example.com")
        with mock.patch.object(gerrit_module, "_is_host_safe", return_value=(False, "internal IP")):
            result = _driver(config).run("changes", [])

        assert isinstance(result.raised, gerrit_module.GerritHostNotAllowedError)
        assert result.requests == []


class TestGerritSourceResponse:
    def test_changes_response_shape(self):
        result = _driver().run("changes", [_response(text=")]}'\n[]")])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == "changes"
        assert response.primary_keys == ["id"]
        # Gerrit returns changes newest-first, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"


class TestValidateCredentials:
    def _validate(
        self, responses: list[ScriptedResponse], **kwargs: Any
    ) -> tuple[bool, str | None, list[RecordedRequest]]:
        with scripted_network(responses) as network:
            valid, error = validate_credentials(
                host=kwargs.pop("host", "https://gerrit.example.com"),
                username=kwargs.pop("username", "reviewbot"),
                http_password=kwargs.pop("http_password", "secret"),
                team_id=kwargs.pop("team_id", 1),
                **kwargs,
            )
        return valid, error, network.requests_log

    def test_anonymous_probe_uses_server_version(self):
        valid, error, requests_log = self._validate(
            [_response(text=')]}\'\n"3.10.0"')],
            username=None,
            http_password=None,
        )
        assert (valid, error) == (True, None)
        assert requests_log[0].url == "https://gerrit.example.com/config/server/version"

    def test_401_is_invalid(self):
        valid, error, _ = self._validate([_response(status_code=401, text="Unauthorized")])
        assert valid is False
        assert error is not None and "HTTP password" in error

    def test_403_passes_at_source_create_but_fails_per_schema(self):
        assert self._validate([_response(status_code=403)])[0] is True
        valid, error, _ = self._validate([_response(status_code=403)], schema_name="groups")
        assert valid is False
        assert error is not None and "permission" in error

    def test_redirect_is_rejected(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://other.example.com"})
        valid, error, _ = self._validate([redirect])
        assert (valid, error) == (False, HOST_NOT_ALLOWED_ERROR)

    def test_non_json_200_is_rejected(self):
        valid, error, _ = self._validate([_response(text="<html>a login page</html>")])
        assert valid is False
        assert error is not None and "valid API response" in error

    def test_oversized_response_body_is_rejected(self):
        with mock.patch.object(gerrit_module, "MAX_RESPONSE_BYTES", 8):
            valid, error, _ = self._validate([_response(text=')]}\'\n{"_account_id": 1, "padding": "xxxxxxxxxx"}')])
        assert valid is False
        assert error is not None and "large" in error

    def test_username_without_password_is_rejected_without_a_request(self):
        valid, error, requests_log = self._validate([], http_password=None)
        assert valid is False
        assert error is not None and "both" in error
        assert requests_log == []

    def test_unsafe_host_is_rejected(self):
        with mock.patch.object(gerrit_module, "_is_host_safe", return_value=(False, "internal IP")):
            valid, error, requests_log = self._validate(
                [], host="https://internal.example.com", username=None, http_password=None
            )
        assert (valid, error) == (False, "internal IP")
        assert requests_log == []
