from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualysvmdr import (
    QualysVmdrSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.qualys_vmdr import (
    MISSING_GATEWAY_ERROR,
    QualysVmdrResponseTooLargeError,
    QualysVmdrResumeConfig,
    QualysVmdrRetryableError,
    _build_initial_url,
    _extract_rows,
    _fetch_jwt,
    _fetch_page,
    _parse_xml,
    _read_capped_body,
    build_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.settings import QUALYS_VMDR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source import QualysVmdrSource

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


ASSET_GROUP_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<ASSET_GROUP_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <ASSET_GROUP_LIST>
      <ASSET_GROUP>
        <ID>501</ID>
        <TITLE><![CDATA[Web servers]]></TITLE>
        <OWNER_USER_ID>77</OWNER_USER_ID>
        <IP_SET>
          <IP_RANGE>10.0.0.1-10.0.0.9</IP_RANGE>
          <IP>10.0.1.5</IP>
        </IP_SET>
        <HOST_IDS>1001, 1002</HOST_IDS>
      </ASSET_GROUP>
    </ASSET_GROUP_LIST>
  </RESPONSE>
</ASSET_GROUP_LIST_OUTPUT>"""

REPORT_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<REPORT_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <REPORT_LIST>
      <REPORT>
        <ID>9001</ID>
        <TITLE><![CDATA[Weekly scan]]></TITLE>
        <TYPE>Scan</TYPE>
        <LAUNCH_DATETIME>2026-07-14T08:00:00Z</LAUNCH_DATETIME>
        <STATUS>
          <STATE>Finished</STATE>
        </STATUS>
      </REPORT>
    </REPORT_LIST>
  </RESPONSE>
</REPORT_LIST_OUTPUT>"""

APPLIANCE_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<APPLIANCE_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <APPLIANCE_LIST>
      <APPLIANCE>
        <ID>301</ID>
        <NAME>scanner-a</NAME>
        <STATUS>Online</STATUS>
        <TYPE>Virtual</TYPE>
        <ACTIVATION_CODE>00000000000000</ACTIVATION_CODE>
        <INTERFACE_SETTINGS>
          <INTERFACE>lan</INTERFACE>
          <IP_ADDRESS>10.0.9.1</IP_ADDRESS>
        </INTERFACE_SETTINGS>
      </APPLIANCE>
    </APPLIANCE_LIST>
  </RESPONSE>
</APPLIANCE_LIST_OUTPUT>"""

IP_LIST_PAGE = """<?xml version="1.0" encoding="UTF-8" ?>
<IP_LIST_OUTPUT>
  <RESPONSE>
    <DATETIME>2026-07-15T00:00:00Z</DATETIME>
    <IP_SET>
      <IP>10.0.1.5</IP>
      <IP_RANGE>10.0.0.1-10.0.0.9</IP_RANGE>
      <IP> </IP>
    </IP_SET>
  </RESPONSE>
</IP_LIST_OUTPUT>"""


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


def _config(gateway_server: str | None = None, api_server: str = "qualysapi.qualys.com") -> QualysVmdrSourceConfig:
    return QualysVmdrSourceConfig(
        api_server=api_server, username="user", password="pass", gateway_server=gateway_server
    )


def _drive(
    endpoint: str, script: Script, *, config: QualysVmdrSourceConfig | None = None, **inputs: Any
) -> DriveResult:
    return SourceDriver(QualysVmdrSource(), config or _config()).run(endpoint, script, **inputs)


def _xml(text: str, status: int = 200, headers: dict[str, str] | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, body=text.encode(), headers=headers or {})


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

    def test_extract_detection_rows_flatten_one_row_per_detection_with_host_prefix(self):
        root = _parse_xml(DETECTION_PAGE)
        rows = list(_extract_rows(root, QUALYS_VMDR_ENDPOINTS["host_list_detection"]))

        assert [row["unique_vuln_id"] for row in rows] == ["111", "112"]
        assert all(row["host_id"] == "1001" and row["host_ip"] == "10.0.0.1" for row in rows)
        assert rows[0]["last_update_datetime"] == "2026-07-01T00:00:00Z"
        # The host's DETECTION_LIST must not leak into the flattened row
        assert "host_detection_list" not in rows[0]

    def test_get_rows_paginates_and_saves_state_after_yield(self):
        result = _drive("hosts", [_xml(HOST_LIST_PAGE_1), _xml(HOST_LIST_PAGE_2)], api_version="2.0")

        assert result.raised is None
        assert [[row["id"] for row in batch] for batch in result.items] == [["1001"], ["1002"]]
        assert result.params("id_min") == [None, "1002"]
        # State is saved only for the non-final page, after its batch was yielded
        assert len(result.saved_states) == 1
        assert "id_min=1002" in result.saved_states[0].next_url

    @pytest.mark.parametrize(
        "endpoint,body,expected_path,expected_params,expected_rows",
        [
            (
                "asset_groups",
                ASSET_GROUP_PAGE,
                "/api/2.0/fo/asset/group/",
                {"action": "list", "show_attributes": "ALL", "truncation_limit": "1000"},
                [
                    {
                        "id": "501",
                        "title": "Web servers",
                        "owner_user_id": "77",
                        "ip_set": '{"ip_range": "10.0.0.1-10.0.0.9", "ip": "10.0.1.5"}',
                        "host_ids": "1001, 1002",
                    }
                ],
            ),
            (
                "reports",
                REPORT_PAGE,
                "/api/3.0/fo/report/",
                {"action": "list", "truncation_limit": None},
                [
                    {
                        "id": "9001",
                        "title": "Weekly scan",
                        "type": "Scan",
                        "launch_datetime": "2026-07-14T08:00:00Z",
                        "status": '{"state": "Finished"}',
                    }
                ],
            ),
            (
                "appliances",
                APPLIANCE_PAGE,
                "/api/2.0/fo/appliance/",
                {"action": "list", "output_mode": "full", "truncation_limit": None},
                [
                    {
                        "id": "301",
                        "name": "scanner-a",
                        "status": "Online",
                        "type": "Virtual",
                        "interface_settings": '{"interface": "lan", "ip_address": "10.0.9.1"}',
                    }
                ],
            ),
            (
                "ips",
                IP_LIST_PAGE,
                "/api/2.0/fo/asset/ip/",
                {"action": "list", "truncation_limit": None},
                [
                    {"ip_range": "10.0.1.5", "start_ip": "10.0.1.5", "end_ip": "10.0.1.5"},
                    {"ip_range": "10.0.0.1-10.0.0.9", "start_ip": "10.0.0.1", "end_ip": "10.0.0.9"},
                ],
            ),
        ],
    )
    @pytest.mark.parametrize("api_version", ["2.0", "4.0"])
    def test_get_rows_lookup_endpoints_request_shape_and_rows(
        self, api_version, endpoint, body, expected_path, expected_params, expected_rows
    ):
        result = _drive(endpoint, [_xml(body)], api_version=api_version)

        assert result.raised is None
        assert result.paths == [expected_path]
        assert {name: result.params(name)[0] for name in expected_params} == expected_params
        assert result.rows == expected_rows
        assert result.requests[0].headers["authorization"].startswith("Basic ")

    def test_get_rows_resumes_from_saved_state(self):
        resume_url = "https://qualysapi.qualys.com/api/2.0/fo/asset/host/?action=list&id_min=1002"

        result = _drive(
            "hosts",
            [_xml(HOST_LIST_PAGE_2)],
            api_version="2.0",
            resume_state=QualysVmdrResumeConfig(next_url=resume_url),
        )

        assert result.urls == [resume_url]
        assert [row["id"] for row in result.rows] == ["1002"]

    def test_get_rows_rejects_disallowed_api_server_before_any_request(self):
        result = _drive("hosts", [], config=_config(api_server="169.254.169.254"), api_version="2.0")

        assert isinstance(result.raised, ValueError)
        assert "Qualys API server URL is not allowed" in str(result.raised)
        assert result.requests == []

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
            (403, True),  # authenticated but missing the asset-list scope — still a valid credential
            (409, True),  # rate limited — the credential authenticated
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        with scripted_network(always(_xml("<x/>", status=status_code))) as network:
            ok, error = validate_credentials("qualysapi.qualys.com", "user", "pass")

        assert ok is expected
        assert (error is None) is expected
        assert network.requests_log[0].path == "/api/2.0/fo/asset/host/"
        assert network.requests_log[0].param("truncation_limit") == "1"

    def test_validate_credentials_rejects_disallowed_api_server_before_any_request(self):
        with scripted_network([]) as network:
            ok, error = validate_credentials("localhost", "user", "pass")

        assert ok is False
        assert error is not None and "not allowed" in error
        assert network.requests_log == []

    def test_get_rows_knowledge_base_4_0_mints_jwt_and_uses_bearer(self):
        result = _drive(
            "knowledge_base",
            route({"/auth": [_xml("jwt-token")], "/api/4.0/fo/knowledge_base/vuln/": [_xml(KNOWLEDGE_BASE_PAGE)]}),
            config=_config(gateway_server="gateway.qg2.apps.qualys.com"),
            api_version="4.0",
        )

        # The JWT is minted at the gateway host, then threaded into the request session as a Bearer token
        auth_request, data_request = result.requests
        assert auth_request.method == "POST"
        assert auth_request.url == "https://gateway.qg2.apps.qualys.com/auth"
        assert b"token=true" in (auth_request.body or b"")
        assert data_request.headers["authorization"] == "Bearer jwt-token"
        # KnowledgeBase 4.0 is served from the FO host on the /api/4.0/ path
        assert data_request.url.startswith("https://qualysapi.qualys.com/api/4.0/fo/knowledge_base/vuln/")
        assert [row["qid"] for row in result.rows] == ["38170"]

    def test_get_rows_knowledge_base_4_0_without_gateway_raises_before_any_request(self):
        result = _drive("knowledge_base", [], config=_config(gateway_server=None), api_version="4.0")

        assert isinstance(result.raised, ValueError)
        assert MISSING_GATEWAY_ERROR in str(result.raised)
        assert result.requests == []
        assert result.session_options == []

    def test_fetch_jwt_refuses_an_oversized_gateway_body(self):
        # `gateway_server` is user-supplied, so a host that returns a huge (or slow-dripped) body
        # must not be able to exhaust a shared worker's memory.
        with (
            scripted_network([ScriptedResponse(body=b"a" * 2048)]),
            mock.patch(f"{_MODULE}.MAX_JWT_RESPONSE_BYTES", 1500),
            pytest.raises(QualysVmdrResponseTooLargeError),
        ):
            _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

    def test_fetch_jwt_raises_on_empty_token(self):
        with scripted_network([_xml("   ")]), pytest.raises(ValueError, match="empty JWT"):
            _fetch_jwt("gateway.qg2.apps.qualys.com", "user", "pass", mock.MagicMock())

    def test_fetch_jwt_rejects_disallowed_gateway_before_any_request(self):
        with scripted_network([]) as network, pytest.raises(ValueError, match="not allowed"):
            _fetch_jwt("169.254.169.254", "user", "pass", mock.MagicMock())

        assert network.requests_log == []


class TestQualysVmdrGatewayBodyClose:
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
