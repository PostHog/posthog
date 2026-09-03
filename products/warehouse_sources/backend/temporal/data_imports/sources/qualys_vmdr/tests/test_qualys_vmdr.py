import json
from datetime import UTC, date, datetime
from typing import cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.qualys_vmdr import (
    MISSING_GATEWAY_ERROR,
    QualysVmdrResponseTooLargeError,
    QualysVmdrResumeConfig,
    QualysVmdrRetryableError,
    _build_initial_url,
    _extract_rows,
    _fetch_jwt,
    _fetch_page,
    _next_batch_url,
    _parse_xml,
    _read_capped_body,
    build_base_url,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.settings import QUALYS_VMDR_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.qualys_vmdr"

# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# asserted without sitting through retry backoff.
_fetch_page_unwrapped = _fetch_page.__wrapped__  # type: ignore[attr-defined]

HOST_LIST_PAGE_1 = """<?xml version="1.0" encoding="UTF-8" ?>
<HOST_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <HOST_LIST>
      <HOST>
        <ID>1001</ID>
        <IP>10.0.0.1</IP>
        <TRACKING_METHOD>IP</TRACKING_METHOD>
        <LAST_VULN_SCAN_DATETIME>2026-07-01T10:00:00Z</LAST_VULN_SCAN_DATETIME>
        <TAGS>
          <TAG>
            <TAG_ID>1</TAG_ID>
            <NAME>prod</NAME>
          </TAG>
          <TAG>
            <TAG_ID>2</TAG_ID>
            <NAME>web</NAME>
          </TAG>
        </TAGS>
      </HOST>
    </HOST_LIST>
    <WARNING>
      <CODE>1980</CODE>
      <TEXT>1 record limit exceeded. Use URL to get next batch of results.</TEXT>
      <URL><![CDATA[https://qualysapi.qualys.com/api/2.0/fo/asset/host/?action=list&details=All&truncation_limit=1000&id_min=1002]]></URL>
    </WARNING>
  </RESPONSE>
</HOST_LIST_OUTPUT>"""

HOST_LIST_PAGE_2 = """<?xml version="1.0" encoding="UTF-8" ?>
<HOST_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:01Z</DATETIME>
    <HOST_LIST>
      <HOST>
        <ID>1002</ID>
        <IP>10.0.0.2</IP>
      </HOST>
    </HOST_LIST>
  </RESPONSE>
</HOST_LIST_OUTPUT>"""

DETECTION_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<HOST_LIST_VM_DETECTION_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <HOST_LIST>
      <HOST>
        <ID>1001</ID>
        <IP>10.0.0.1</IP>
        <DETECTION_LIST>
          <DETECTION>
            <UNIQUE_VULN_ID>111</UNIQUE_VULN_ID>
            <QID>38170</QID>
            <STATUS>Active</STATUS>
            <FIRST_FOUND_DATETIME>2026-01-01T00:00:00Z</FIRST_FOUND_DATETIME>
            <LAST_UPDATE_DATETIME>2026-07-01T00:00:00Z</LAST_UPDATE_DATETIME>
          </DETECTION>
          <DETECTION>
            <UNIQUE_VULN_ID>112</UNIQUE_VULN_ID>
            <QID>91234</QID>
            <STATUS>New</STATUS>
          </DETECTION>
        </DETECTION_LIST>
      </HOST>
    </HOST_LIST>
  </RESPONSE>
</HOST_LIST_VM_DETECTION_OUTPUT>"""

SIMPLE_RETURN_ERROR = """<?xml version="1.0" encoding="UTF-8" ?>
<SIMPLE_RETURN>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <CODE>2011</CODE>
    <TEXT>Bad parameter value</TEXT>
  </RESPONSE>
</SIMPLE_RETURN>"""

KNOWLEDGE_BASE_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<KNOWLEDGE_BASE_VULN_LIST_OUTPUT>
  <RESPONSE>
    <VULN_LIST>
      <VULN>
        <QID>38170</QID>
        <TITLE>Example vulnerability</TITLE>
      </VULN>
    </VULN_LIST>
  </RESPONSE>
</KNOWLEDGE_BASE_VULN_LIST_OUTPUT>"""


def _response(status_code: int = 200, text: str = "", headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = text
    response.encoding = "utf-8"
    # _fetch_page reads the body via stream=True + iter_content, not response.text.
    response.iter_content.return_value = iter([text.encode("utf-8")]) if text else iter([])
    response.headers = headers or {}
    response.url = "https://qualysapi.qualys.com/api/2.0/fo/asset/host/"
    return response


class _FakeManager:
    def __init__(self, state: QualysVmdrResumeConfig | None = None):
        self.state = state
        self.saved: list[QualysVmdrResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> QualysVmdrResumeConfig | None:
        return self.state

    def save_state(self, data: QualysVmdrResumeConfig) -> None:
        self.saved.append(data)

    def as_manager(self) -> ResumableSourceManager[QualysVmdrResumeConfig]:
        return cast(ResumableSourceManager[QualysVmdrResumeConfig], self)


class TestQualysVmdr:
    @pytest.mark.parametrize(
        "api_server,expected",
        [
            ("qualysapi.qualys.com", "https://qualysapi.qualys.com"),
            ("https://qualysapi.qualys.eu/", "https://qualysapi.qualys.eu"),
            ("http://qualysapi.qg2.apps.qualys.com", "https://qualysapi.qg2.apps.qualys.com"),
            (" qualysapi.qualys.ca ", "https://qualysapi.qualys.ca"),
        ],
    )
    def test_build_base_url_normalizes_and_forces_https(self, api_server, expected):
        assert build_base_url(api_server) == expected

    @pytest.mark.parametrize(
        "value,expected_param",
        [
            (datetime(2026, 7, 1, 10, 30, 0, tzinfo=UTC), "vm_scan_since=2026-07-01T10%3A30%3A00Z"),
            (date(2026, 7, 1), "vm_scan_since=2026-07-01T00%3A00%3A00Z"),
        ],
    )
    def test_initial_url_includes_incremental_filter(self, value, expected_param):
        url = _build_initial_url("https://example.com", QUALYS_VMDR_ENDPOINTS["hosts"], "2.0", True, value)
        assert expected_param in url
        assert "truncation_limit=1000" in url

    def test_initial_url_full_refresh_has_no_incremental_filter(self):
        url = _build_initial_url("https://example.com", QUALYS_VMDR_ENDPOINTS["hosts"], "2.0", False, None)
        assert "vm_scan_since" not in url

    def test_initial_url_omits_truncation_limit_when_endpoint_does_not_support_it(self):
        url = _build_initial_url("https://example.com", QUALYS_VMDR_ENDPOINTS["scans"], "2.0", False, None)
        assert "truncation_limit" not in url
        assert url.startswith("https://example.com/api/2.0/fo/scan/?")

    @pytest.mark.parametrize(
        "endpoint,api_version,expected_path",
        [
            # Only the KnowledgeBase endpoint moves to /api/4.0/ under the 4.0 pin.
            ("knowledge_base", "2.0", "/api/2.0/fo/knowledge_base/vuln/"),
            ("knowledge_base", "4.0", "/api/4.0/fo/knowledge_base/vuln/"),
            # The FO endpoints stay on /api/2.0/ regardless of the source-level pin.
            ("hosts", "2.0", "/api/2.0/fo/asset/host/"),
            ("hosts", "4.0", "/api/2.0/fo/asset/host/"),
            ("scans", "4.0", "/api/2.0/fo/scan/"),
        ],
    )
    def test_initial_url_resolves_path_per_version(self, endpoint, api_version, expected_path):
        url = _build_initial_url("https://example.com", QUALYS_VMDR_ENDPOINTS[endpoint], api_version, False, None)
        assert url.startswith(f"https://example.com{expected_path}?")

    def test_extract_rows_lowercases_scalars_and_json_encodes_nested(self):
        root = _parse_xml(HOST_LIST_PAGE_1)
        rows = list(_extract_rows(root, QUALYS_VMDR_ENDPOINTS["hosts"]))

        assert len(rows) == 1
        assert rows[0]["id"] == "1001"
        assert rows[0]["last_vuln_scan_datetime"] == "2026-07-01T10:00:00Z"
        # Repeated nested elements are JSON strings, not structs (arrow type stability)
        tags = json.loads(rows[0]["tags"])
        assert [t["name"] for t in tags["tag"]] == ["prod", "web"]

    def test_extract_detection_rows_flatten_one_row_per_detection_with_host_prefix(self):
        root = _parse_xml(DETECTION_PAGE)
        rows = list(_extract_rows(root, QUALYS_VMDR_ENDPOINTS["host_list_detection"]))

        assert [row["unique_vuln_id"] for row in rows] == ["111", "112"]
        assert all(row["host_id"] == "1001" and row["host_ip"] == "10.0.0.1" for row in rows)
        assert rows[0]["last_update_datetime"] == "2026-07-01T00:00:00Z"
        # The host's DETECTION_LIST must not leak into the flattened row
        assert "host_detection_list" not in rows[0]

    def test_parse_xml_tolerates_keepalive_whitespace(self):
        root = _parse_xml("\n   \n" + HOST_LIST_PAGE_2)
        assert root.tag == "HOST_LIST_OUTPUT"

    def test_next_batch_url_is_rerooted_onto_configured_server(self):
        root = _parse_xml(HOST_LIST_PAGE_1)
        next_url = _next_batch_url(root, "https://qualysapi.qualys.eu")

        assert next_url is not None
        assert next_url.startswith("https://qualysapi.qualys.eu/api/2.0/fo/asset/host/?")
        assert "id_min=1002" in next_url

    def test_next_batch_url_none_without_warning(self):
        assert _next_batch_url(_parse_xml(HOST_LIST_PAGE_2), "https://example.com") is None

    def test_get_rows_paginates_and_saves_state_after_yield(self):
        manager = _FakeManager()
        session = mock.MagicMock()
        session.get.side_effect = [_response(text=HOST_LIST_PAGE_1), _response(text=HOST_LIST_PAGE_2)]

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            generator = get_rows(
                "qualysapi.qualys.com", "user", "pass", "hosts", "2.0", mock.MagicMock(), manager.as_manager()
            )

            first_batch = next(generator)
            assert [row["id"] for row in first_batch] == ["1001"]
            # State is saved only once the consumer resumes after the yield — a crash while the
            # batch is being processed re-yields it instead of skipping it
            assert len(manager.saved) == 0

            second_batch = next(generator)
            assert [row["id"] for row in second_batch] == ["1002"]
            assert len(manager.saved) == 1
            assert "id_min=1002" in manager.saved[0].next_url
            with pytest.raises(StopIteration):
                next(generator)

        # No further state saved for the final page
        assert len(manager.saved) == 1

    def test_get_rows_resumes_from_saved_state(self):
        resume_url = "https://qualysapi.qualys.com/api/2.0/fo/asset/host/?action=list&id_min=1002"
        manager = _FakeManager(state=QualysVmdrResumeConfig(next_url=resume_url))
        session = mock.MagicMock()
        session.get.return_value = _response(text=HOST_LIST_PAGE_2)

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            batches = list(
                get_rows("qualysapi.qualys.com", "user", "pass", "hosts", "2.0", mock.MagicMock(), manager.as_manager())
            )

        assert session.get.call_args[0][0] == resume_url
        assert [row["id"] for row in batches[0]] == ["1002"]

    def test_get_rows_rejects_disallowed_api_server_before_any_request(self):
        session = mock.MagicMock()

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(False, "URL resolves to a private IP")),
        ):
            with pytest.raises(ValueError, match="Qualys API server URL is not allowed"):
                list(
                    get_rows(
                        "169.254.169.254", "user", "pass", "hosts", "2.0", mock.MagicMock(), _FakeManager().as_manager()
                    )
                )

        session.get.assert_not_called()

    def test_fetch_page_rate_limit_carries_server_wait(self):
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=409, headers={"X-RateLimit-ToWait-Sec": "42"})

        with pytest.raises(QualysVmdrRetryableError) as exc_info:
            _fetch_page_unwrapped(session, "https://example.com", mock.MagicMock())

        assert exc_info.value.wait_seconds == 42

    def test_read_capped_body_refuses_bodies_over_the_size_cap(self):
        # A user-controlled host must not be able to make us buffer an unbounded body — the cap
        # aborts the read (and closes the response) instead of holding it all in memory.
        response = mock.MagicMock()
        response.iter_content.return_value = iter([b"a" * 1024, b"b" * 1024])

        with mock.patch(f"{_MODULE}.MAX_RESPONSE_BYTES", 1500):
            with pytest.raises(QualysVmdrResponseTooLargeError):
                _read_capped_body(response)

        response.close.assert_called_once()

    def test_fetch_page_raises_on_simple_return_error_document(self):
        session = mock.MagicMock()
        session.get.return_value = _response(text=SIMPLE_RETURN_ERROR)

        with pytest.raises(ValueError, match="Bad parameter value"):
            _fetch_page_unwrapped(session, "https://example.com", mock.MagicMock())

    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (200, True),
            (403, True),  # authenticated but missing the asset-list scope — still a valid credential
            (409, True),  # rate limited — the credential authenticated
            (401, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=status_code, text="<x/>")

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            ok, error = validate_credentials("qualysapi.qualys.com", "user", "pass")

        assert ok is expected
        assert (error is None) is expected

    def test_validate_credentials_false_on_connection_error(self):
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("dns failure")

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            ok, error = validate_credentials("nonexistent.example.com", "user", "pass")

        assert ok is False
        assert error is not None

    def test_validate_credentials_rejects_disallowed_api_server_before_any_request(self):
        session = mock.MagicMock()

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(False, "URL resolves to a private IP")),
        ):
            ok, error = validate_credentials("localhost", "user", "pass")

        assert ok is False
        assert error is not None and "not allowed" in error
        session.get.assert_not_called()

    def test_get_rows_knowledge_base_4_0_mints_jwt_and_uses_bearer(self):
        get_session = mock.MagicMock()
        get_session.get.return_value = _response(text=KNOWLEDGE_BASE_PAGE)
        gateway_session = mock.MagicMock()
        gateway_session.post.return_value = _response(status_code=200, text="jwt-token")

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=get_session) as make_session,
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            batches = list(
                get_rows(
                    "qualysapi.qualys.com",
                    "user",
                    "pass",
                    "knowledge_base",
                    "4.0",
                    mock.MagicMock(),
                    _FakeManager().as_manager(),
                    gateway_server="gateway.qg2.apps.qualys.com",
                )
            )

        # The JWT is minted at the gateway host, then threaded into the request session as a Bearer token
        assert gateway_session.post.call_args[0][0] == "https://gateway.qg2.apps.qualys.com/auth"
        assert gateway_session.post.call_args.kwargs["data"]["token"] == "true"
        assert make_session.call_args.kwargs["bearer_token"] == "jwt-token"
        # KnowledgeBase 4.0 is served from the FO host on the /api/4.0/ path
        assert get_session.get.call_args[0][0].startswith(
            "https://qualysapi.qualys.com/api/4.0/fo/knowledge_base/vuln/"
        )
        assert [row["qid"] for row in batches[0]] == ["38170"]

    def test_get_rows_knowledge_base_2_0_uses_basic_auth_and_2_0_path(self):
        get_session = mock.MagicMock()
        get_session.get.return_value = _response(text=KNOWLEDGE_BASE_PAGE)

        with (
            mock.patch(f"{_MODULE}._make_session", return_value=get_session) as make_session,
            mock.patch(f"{_MODULE}.make_tracked_session") as gateway,
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            list(
                get_rows(
                    "qualysapi.qualys.com",
                    "user",
                    "pass",
                    "knowledge_base",
                    "2.0",
                    mock.MagicMock(),
                    _FakeManager().as_manager(),
                )
            )

        # No JWT minting on 2.0 — the request session keeps basic auth
        gateway.assert_not_called()
        assert "bearer_token" not in make_session.call_args.kwargs
        assert get_session.get.call_args[0][0].startswith(
            "https://qualysapi.qualys.com/api/2.0/fo/knowledge_base/vuln/"
        )

    def test_get_rows_knowledge_base_4_0_without_gateway_raises_before_any_request(self):
        with (
            mock.patch(f"{_MODULE}._make_session") as make_session,
            mock.patch(f"{_MODULE}.make_tracked_session") as gateway,
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            with pytest.raises(ValueError, match=MISSING_GATEWAY_ERROR):
                list(
                    get_rows(
                        "qualysapi.qualys.com",
                        "user",
                        "pass",
                        "knowledge_base",
                        "4.0",
                        mock.MagicMock(),
                        _FakeManager().as_manager(),
                        gateway_server=None,
                    )
                )

        gateway.assert_not_called()
        make_session.assert_not_called()

    def test_fetch_jwt_posts_credentials_to_gateway_and_strips_token(self):
        gateway_session = mock.MagicMock()
        gateway_session.post.return_value = _response(status_code=200, text="  jwt-token\n")

        with (
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            token = _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

        assert token == "jwt-token"
        assert gateway_session.post.call_args[0][0] == "https://gateway.qg2.apps.qualys.com/auth"
        assert gateway_session.post.call_args.kwargs["data"] == {
            "username": "user",
            "password": "pass",
            "token": "true",
        }

    def test_fetch_jwt_session_opts_out_of_sample_capture(self):
        # The /auth response body is the raw minted JWT: the name-based sample scrubbers can't
        # recognise it and it can't be listed in `redact_values` (it doesn't exist yet), so the
        # exchange must be excluded from HTTP sample capture entirely.
        gateway_session = mock.MagicMock()
        gateway_session.post.return_value = _response(status_code=200, text="jwt-token")

        with (
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session) as make_tracked,
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

        assert make_tracked.call_args.kwargs["capture"] is False
        # The password is still redacted from the metered request, and the body is streamed
        # rather than buffered whole.
        assert make_tracked.call_args.kwargs["redact_values"] == ("pass",)
        assert gateway_session.post.call_args.kwargs["stream"] is True

    def test_fetch_jwt_refuses_an_oversized_gateway_body(self):
        # `gateway_server` is user-supplied, so a host that returns a huge (or slow-dripped) body
        # must not be able to exhaust a shared worker's memory.
        gateway_session = mock.MagicMock()
        response = _response(status_code=200)
        response.iter_content.return_value = iter([b"a" * 1024, b"b" * 1024])
        gateway_session.post.return_value = response

        with (
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
            mock.patch(f"{_MODULE}.MAX_JWT_RESPONSE_BYTES", 1500),
        ):
            with pytest.raises(QualysVmdrResponseTooLargeError):
                _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

        response.close.assert_called_once()

    def test_fetch_jwt_raises_on_empty_token(self):
        gateway_session = mock.MagicMock()
        gateway_session.post.return_value = _response(status_code=200, text="   ")

        with (
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None)),
        ):
            with pytest.raises(ValueError, match="empty JWT"):
                _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

    def test_fetch_jwt_rejects_disallowed_gateway_before_any_request(self):
        gateway_session = mock.MagicMock()

        with (
            mock.patch(f"{_MODULE}.make_tracked_session", return_value=gateway_session),
            mock.patch(f"{_MODULE}.is_url_allowed", return_value=(False, "URL resolves to a private IP")),
        ):
            with pytest.raises(ValueError, match="not allowed"):
                _fetch_jwt("169.254.169.254", "user", "pass", mock.MagicMock())

        gateway_session.post.assert_not_called()
