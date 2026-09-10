import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.moxie import moxie as moxie_module
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.moxie import (
    MoxieHostNotAllowedError,
    moxie_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import ENDPOINTS, MOXIE_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the moxie module.
MOXIE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.moxie.moxie.make_tracked_session"
)

BASE_URL = "https://pod00.withmoxie.dev/api/public"


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's URL + auth headers at prepare time."""
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.headers = {}
        if request.auth is not None:
            request.auth(prepared)
        seen.append({"url": request.url, "auth_headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _source(endpoint: str, base_url: str = BASE_URL, team_id: int = 1) -> Any:
    return moxie_source(base_url, "test_key", endpoint, team_id=team_id, job_id="j")


def _batches(source_response: Any) -> list[list[dict[str, Any]]]:
    return [list(page) for page in source_response.items()]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://pod00.withmoxie.dev/api/public", "https://pod00.withmoxie.dev/api/public"),
            ("https://pod00.withmoxie.dev/api/public/", "https://pod00.withmoxie.dev/api/public"),
            ("pod00.withmoxie.dev", "https://pod00.withmoxie.dev/api/public"),
            ("http://pod00.withmoxie.dev", "http://pod00.withmoxie.dev/api/public"),
            ("  https://pod00.withmoxie.dev/api/public  ", "https://pod00.withmoxie.dev/api/public"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalizes_variants(self, raw: str | None, expected: str) -> None:
        assert normalize_base_url(raw) == expected


class TestMoxieTransport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_object_endpoint_yields_single_batch_with_api_key_header(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        seen = _wire(session, [_response([{"id": "1"}, {"id": "2"}])])

        batches = _batches(_source("contacts"))

        assert batches == [[{"id": "1"}, {"id": "2"}]]
        # No pagination anywhere on Moxie's API — exactly one request per endpoint.
        assert session.send.call_count == 1
        assert seen[0]["url"] == f"{BASE_URL}/action/contacts/search"
        assert seen[0]["auth_headers"]["X-API-KEY"] == "test_key"

    @pytest.mark.parametrize("endpoint", ["email_templates", "invoice_templates", "vendor_names", "form_names"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_scalar_endpoints_wrap_bare_strings_into_rows(self, MockSession: mock.MagicMock, endpoint: str) -> None:
        session = MockSession.return_value
        _wire(session, [_response(["Template A", "Template B"])])

        batches = _batches(_source(endpoint))

        assert batches == [[{"name": "Template A"}, {"name": "Template B"}]]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_workspace_users_flattens_nested_user_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        row = {"userType": "OWNER", "user": {"userId": 42, "firstName": "Alex"}}
        _wire(session, [_response([row])])

        batches = _batches(_source("workspace_users"))

        assert batches == [[{**row, "user_id": 42}]]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_host_check_blocks_before_any_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(MoxieHostNotAllowedError, match="internal address"):
                _batches(_source("clients"))

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plaintext_http_is_rejected_before_any_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        with pytest.raises(MoxieHostNotAllowedError, match="HTTPS"):
            _batches(_source("clients", base_url="http://pod00.withmoxie.dev/api/public"))

        session.send.assert_not_called()


class TestSourceResponseConfig:
    def test_all_endpoints_buildable_with_declared_keys(self) -> None:
        for endpoint in ENDPOINTS:
            response = _source(endpoint)
            assert response.name == endpoint
            assert response.primary_keys == MOXIE_ENDPOINTS[endpoint].primary_keys

    def test_projects_and_invoices_partition_on_a_stable_creation_field(self) -> None:
        for endpoint in ("projects", "payable_invoices"):
            response = _source(endpoint)
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == ["dateCreated"]

    def test_endpoints_without_a_creation_field_are_unpartitioned(self) -> None:
        for endpoint in ("clients", "contacts", "email_templates", "workspace_users"):
            response = _source(endpoint)
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(MOXIE_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status: int, expected_valid: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        is_valid, _message = validate_credentials(BASE_URL, "test_key", team_id=1)
        assert is_valid is expected_valid

    @mock.patch(MOXIE_SESSION_PATCH)
    def test_connection_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, _message = validate_credentials(BASE_URL, "test_key", team_id=1)
        assert is_valid is False

    @mock.patch(MOXIE_SESSION_PATCH)
    def test_probes_clients_list_with_api_key_header_and_redaction(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials(BASE_URL, "test_key", team_id=1)

        call = mock_session.return_value.get.call_args
        called_url = call.args[0] if call.args else call.kwargs["url"]
        assert called_url == f"{BASE_URL}/action/clients/list"
        assert call.kwargs["headers"]["X-API-KEY"] == "test_key"
        # The key must be registered for redaction in tracked telemetry.
        assert mock_session.call_args.kwargs["redact_values"] == ("test_key",)

    def test_blank_base_url_is_rejected(self) -> None:
        is_valid, message = validate_credentials("", "test_key", team_id=1)
        assert is_valid is False
        assert message == "That doesn't look like a Moxie workspace base URL."

    def test_plaintext_http_is_rejected_before_any_request(self) -> None:
        is_valid, message = validate_credentials("http://pod00.withmoxie.dev/api/public", "test_key", team_id=1)
        assert is_valid is False
        assert message is not None and "HTTPS" in message

    def test_host_not_allowed_is_rejected(self) -> None:
        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            is_valid, message = validate_credentials(BASE_URL, "test_key", team_id=1)
        assert is_valid is False
        assert message == "internal address"
