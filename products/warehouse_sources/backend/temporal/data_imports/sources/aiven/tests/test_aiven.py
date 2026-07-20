import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.aiven import (
    AIVEN_BASE_URL,
    _auth_header_value,
    aiven_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import AIVEN_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aiven module.
AIVEN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aiven.aiven.make_tracked_session"
)


def _response(status_code: int, body: Any) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: MagicMock, responses_by_path: dict[str, requests.Response]) -> list[str]:
    """Wire a mock session that dispatches each request to a response by its (formatted) path.

    Fan-out issues one request per parent row in a deterministic order, but keying by path keeps the
    test robust to ordering. Returns the list of paths requested, in call order.
    """
    session.headers = {}
    requested_paths: list[str] = []

    def _prepare(request: Any) -> MagicMock:
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    def _send(prepared: Any, **kwargs: Any) -> requests.Response:
        path = prepared.url.replace(AIVEN_BASE_URL, "")
        requested_paths.append(path)
        return responses_by_path[path]

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return requested_paths


def _rows(endpoint: str) -> list[dict[str, Any]]:
    response = aiven_source("tok", endpoint, team_id=1, job_id="j")
    return [row for page in response.items() for row in page]


class TestAuthHeader:
    def test_uses_aivenv1_scheme_not_bearer(self) -> None:
        # Aiven requires the literal `aivenv1` prefix; a `Bearer` prefix is rejected by the API.
        value = _auth_header_value("tok-123")
        assert value == "aivenv1 tok-123"
        assert "Bearer" not in value


class TestListExtraction:
    @parameterized.expand(
        [
            ("present", {"projects": [{"project_name": "p1"}]}, [{"project_name": "p1"}]),
            ("missing_key", {"other": []}, []),
            ("null_value", {"projects": None}, []),
            ("empty_list", {"projects": []}, []),
        ]
    )
    @patch(CLIENT_SESSION_PATCH)
    def test_extracts_rows_under_data_key(
        self, _name: str, body: dict[str, Any], expected: list, MockSession: MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, {"/project": _response(200, body)})
        assert _rows("projects") == expected


class TestFanOut:
    @patch(CLIENT_SESSION_PATCH)
    def test_fan_out_none_yields_rows(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, {"/clouds": _response(200, {"clouds": [{"cloud_name": "aws-x"}]})})
        assert _rows("clouds") == [{"cloud_name": "aws-x"}]

    @patch(CLIENT_SESSION_PATCH)
    def test_fan_out_project_injects_parent_project_name(self, MockSession: MagicMock) -> None:
        # `services` items carry no project field, so the parent's `project_name` must be injected
        # to keep the composite primary key unique across projects.
        session = MockSession.return_value
        _wire(
            session,
            {
                "/project": _response(200, {"projects": [{"project_name": "p1"}, {"project_name": "p2"}]}),
                "/project/p1/service": _response(200, {"services": [{"service_name": "s1"}]}),
                "/project/p2/service": _response(200, {"services": [{"service_name": "s2"}]}),
            },
        )
        assert _rows("services") == [
            {"service_name": "s1", "project_name": "p1"},
            {"service_name": "s2", "project_name": "p2"},
        ]

    @patch(CLIENT_SESSION_PATCH)
    def test_fan_out_organization_injects_org(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            {
                "/organizations": _response(200, {"organizations": [{"organization_id": "org1"}]}),
                "/organization/org1/user": _response(200, {"users": [{"user_id": "u1"}]}),
            },
        )
        assert _rows("organization_users") == [{"user_id": "u1", "organization_id": "org1"}]

    @patch(CLIENT_SESSION_PATCH)
    def test_fan_out_organization_setdefault_keeps_existing_org_id(self, MockSession: MagicMock) -> None:
        # billing_groups already carry organization_id; injection must not clobber it.
        session = MockSession.return_value
        _wire(
            session,
            {
                "/organizations": _response(200, {"organizations": [{"organization_id": "org1"}]}),
                "/organization/org1/billing-groups": _response(
                    200, {"billing_groups": [{"billing_group_id": "bg1", "organization_id": "org-real"}]}
                ),
            },
        )
        rows = _rows("billing_groups")
        assert rows == [{"billing_group_id": "bg1", "organization_id": "org-real"}]

    @patch(CLIENT_SESSION_PATCH)
    def test_fan_out_invoice_two_levels_injects_org_and_invoice(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            {
                "/organizations": _response(200, {"organizations": [{"organization_id": "org1"}]}),
                "/organization/org1/invoices": _response(
                    200, {"invoices": [{"invoice_number": "inv1"}, {"invoice_number": "inv2"}]}
                ),
                "/organization/org1/invoice/inv1/lines": _response(200, {"lines": [{"line_type": "usage"}]}),
                "/organization/org1/invoice/inv2/lines": _response(200, {"lines": [{"line_type": "credit"}]}),
            },
        )
        assert _rows("invoice_lines") == [
            {"line_type": "usage", "organization_id": "org1", "invoice_number": "inv1"},
            {"line_type": "credit", "organization_id": "org1", "invoice_number": "inv2"},
        ]

    @patch(CLIENT_SESSION_PATCH)
    def test_empty_child_batches_are_not_yielded(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            {
                "/project": _response(200, {"projects": [{"project_name": "p1"}, {"project_name": "p2"}]}),
                "/project/p1/service": _response(200, {"services": []}),
                "/project/p2/service": _response(200, {"services": [{"service_name": "s2"}]}),
            },
        )
        assert _rows("services") == [{"service_name": "s2", "project_name": "p2"}]


class TestFailLoud:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @patch(CLIENT_SESSION_PATCH)
    def test_client_errors_surface(self, _name: str, status: int, MockSession: MagicMock) -> None:
        # A 4xx is non-retryable and must fail the sync loudly rather than syncing 0 rows silently.
        session = MockSession.return_value
        _wire(session, {"/project": _response(status, {"message": "nope"})})
        with pytest.raises(requests.HTTPError):
            _rows("projects")


class TestSourceResponse:
    @parameterized.expand(list(AIVEN_ENDPOINTS.keys()))
    @patch(CLIENT_SESSION_PATCH)
    def test_source_response_matches_endpoint_settings(self, endpoint: str, MockSession: MagicMock) -> None:
        config = AIVEN_ENDPOINTS[endpoint]
        response = aiven_source("tok", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @patch(AIVEN_SESSION_PATCH)
    def test_maps_status_to_bool(self, _name: str, status: int, expected: bool, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = MagicMock(status_code=status)
        assert validate_credentials("tok") is expected

    @patch(AIVEN_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("tok") is False
