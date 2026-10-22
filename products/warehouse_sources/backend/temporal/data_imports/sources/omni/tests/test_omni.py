import json
from typing import Any

import pytest
from unittest import mock

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omni import OmniSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni import omni as omni_module
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.omni import (
    OmniDocumentsPaginator,
    OmniResumeConfig,
    OmniScimPaginator,
    _format_watermark,
    get_endpoint_permissions,
    get_key_scope,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.settings import PARTITION_KEYS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.source import OmniSource


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://acme.omniapp.co", "https://acme.omniapp.co"),
            ("acme.omniapp.co", "https://acme.omniapp.co"),
            ("https://acme.omniapp.co/api", "https://acme.omniapp.co"),
            ("http://acme.omniapp.co", "https://acme.omniapp.co"),
            ("http://localhost:8080", "http://localhost:8080"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFormatWatermark:
    def test_formats_datetime_with_millisecond_precision(self):
        import datetime

        value = datetime.datetime(2026, 6, 1, 14, 30, 0, 500000, tzinfo=datetime.UTC)
        assert _format_watermark(value) == "2026-06-01T14:30:00.500Z"

    def test_string_value_passed_through(self):
        assert _format_watermark("2026-06-01T14:30:00.000Z") == "2026-06-01T14:30:00.000Z"

    @pytest.mark.parametrize("value", [None, "", 123])
    def test_unsupported_values_return_none(self, value):
        assert _format_watermark(value) is None


class TestOmniDocumentsPaginator:
    def test_full_sync_never_stops_early(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than=None)
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [{"updatedAt": "2020-01-01T00:00:00.000Z"}]
        paginator.update_state(response, data)

        assert paginator.has_next_page is True

    def test_incremental_stops_once_page_predates_watermark(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than="2026-01-01T00:00:00.000Z")
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [
            {"updatedAt": "2025-06-01T00:00:00.000Z"},
            {"updatedAt": "2025-05-01T00:00:00.000Z"},
        ]
        paginator.update_state(response, data)

        assert paginator.has_next_page is False


class TestOmniScimPaginator:
    def test_set_resume_state_seeds_start_index(self):
        paginator = OmniScimPaginator()
        paginator.set_resume_state({"start_index": 201})

        request = Request(method="GET", url="https://acme.omniapp.co/api/scim/v2/users")
        paginator.init_request(request)
        assert request.params["startIndex"] == 201


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "Documents", True),
            (401, None, False),
            (401, "Documents", False),
            (403, None, True),
            (403, "Documents", False),
            (500, None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials("acme.omniapp.co", "test-key", team_id=1, schema_name=schema_name)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/api/v1/whoami"}
        assert all(request.headers["authorization"] == "Bearer test-key" for request in network.requests_log)
        assert network.session_options[0]["allow_redirects"] is False

    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_validate_credentials_blocks_unsafe_host(self, _mock_host_safe):
        is_valid, error = validate_credentials("169.254.169.254", "test-key", team_id=1)

        assert is_valid is False
        assert error == "internal address"

    def test_validate_credentials_rejects_invalid_hostname(self):
        is_valid, error = validate_credentials("not a host!!", "test-key", team_id=1)
        assert is_valid is False
        assert error


class TestGetKeyScope:
    def test_returns_key_scope_on_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"keyScope": "organization"})]) as network:
            assert get_key_scope("acme.omniapp.co", "test-key") == "organization"
        assert [request.path for request in network.requests_log] == ["/api/v1/whoami"]

    def test_returns_none_on_error_status(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            assert get_key_scope("acme.omniapp.co", "test-key") is None

    def test_returns_none_on_request_exception(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            assert get_key_scope("acme.omniapp.co", "test-key") is None


class TestGetEndpointPermissions:
    def test_no_scim_endpoints_requested_returns_all_reachable(self):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Folders"])
        assert result == {"Documents": None, "Folders": None}

    @mock.patch.object(omni_module, "get_key_scope", return_value="user")
    def test_pat_scope_blocks_scim_endpoints(self, _mock_scope):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Users", "UserGroups"])

        assert result["Documents"] is None
        assert result["Users"] is not None
        assert result["UserGroups"] is not None


class TestOmniSourceEndToEnd:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OmniSource(), OmniSourceConfig(host="acme.omniapp.co", api_key="test-key"))

    def test_documents_pagination_and_checkpointing(self) -> None:
        result = self._driver().run(
            "Documents",
            [
                ScriptedResponse(
                    json={
                        "pageInfo": {"hasNextPage": True, "nextCursor": "cursor-1"},
                        "records": [{"identifier": "d1", "updatedAt": "2026-01-02T00:00:00.000Z"}],
                    }
                ),
                ScriptedResponse(
                    json={
                        "pageInfo": {"hasNextPage": False, "nextCursor": None},
                        "records": [{"identifier": "d2", "updatedAt": "2026-01-01T00:00:00.000Z"}],
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 2
        assert result.params("sortField") == ["updatedAt", "updatedAt"]
        assert result.params("sortDirection") == ["desc", "desc"]
        assert result.params("cursor") == [None, "cursor-1"]
        assert result.saved_states == [OmniResumeConfig(cursor="cursor-1")]
        assert result.committed_states == [OmniResumeConfig(cursor="cursor-1")]

    def test_documents_resumes_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "Documents",
            [ScriptedResponse(json={"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": []})],
            resume_state=OmniResumeConfig(cursor="resumed-cursor"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["resumed-cursor"]

    def test_connections_single_page_never_checkpoints(self) -> None:
        result = self._driver().run(
            "Connections", [ScriptedResponse(json={"connections": [{"id": "c1"}, {"id": "c2"}]})]
        )

        assert result.raised is None
        assert result.rows == [{"id": "c1"}, {"id": "c2"}]
        assert result.saved_states == []

    def test_users_scim_pagination_checkpoints_start_index(self) -> None:
        result = self._driver().run(
            "Users",
            [
                ScriptedResponse(
                    json={"Resources": [{"id": "u1"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 1}
                ),
                ScriptedResponse(
                    json={"Resources": [{"id": "u2"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 2}
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "u1"}, {"id": "u2"}]
        assert result.params("startIndex") == ["1", "2"]
        assert result.saved_states == [OmniResumeConfig(start_index=2)]

    @pytest.mark.parametrize("endpoint", list(PRIMARY_KEYS.keys()))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        selector = {
            "Documents": "records",
            "Folders": "records",
            "Connections": "connections",
            "Schedules": "records",
            "Users": "Resources",
            "UserGroups": "Resources",
        }[endpoint]
        body = {"pageInfo": {"hasNextPage": False, "nextCursor": None}, selector: []}
        result = self._driver().run(endpoint, [ScriptedResponse(json=body)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert response.sort_mode == ("desc" if endpoint == "Documents" else "asc")
        partition_key = PARTITION_KEYS[endpoint]
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestOmniSourceSsrfGuards:
    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_sync_rejects_unsafe_host(self, _mock_host_safe: mock.MagicMock) -> None:
        # A hostname that validated publicly can be DNS-rebound to a private address before a
        # scheduled import runs; the sync must re-check rather than trust the stored host.
        result = TestOmniSourceEndToEnd._driver().run("Connections", [])

        assert isinstance(result.raised, ValueError)
        assert "internal address" in str(result.raised)
        assert result.requests == []

    def test_sync_pins_host_and_disables_redirects(self) -> None:
        result = TestOmniSourceEndToEnd._driver().run(
            "Connections",
            [
                ScriptedResponse(
                    status=302,
                    headers={"Location": "https://other.example.com/steal"},
                )
            ],
        )

        # Redirects are never followed, so a 3xx can't bounce the bearer token off-host.
        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
        assert len(result.requests) == 1
        assert result.requests[0].origin == "https://acme.omniapp.co"
        assert result.requests[0].headers["authorization"] == "Bearer test-key"
