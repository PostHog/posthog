import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.vultr import (
    VULTR_PER_PAGE,
    _cursor_paginator,
    _redact_secrets,
    get_resource,
    validate_credentials,
    vultr_source,
)

VULTR_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.vultr.vultr"


def _make_response(json_body: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_matches_settings(self, endpoint: str) -> None:
        config = ENDPOINTS[endpoint]
        resource = get_resource(endpoint)

        assert resource["name"] == config.name
        assert resource["table_name"] == config.name
        assert resource["table_format"] == "delta"
        # Vultr exposes no server-side time filter, so every endpoint is full-refresh.
        assert resource["write_disposition"] == "replace"

        ep = _endpoint(resource)
        assert ep["path"] == config.path
        assert ep["data_selector"] == config.data_selector
        assert ep["params"] == {"per_page": VULTR_PER_PAGE}

    def test_per_page_is_within_vultr_max(self) -> None:
        # Vultr rejects per_page above 500.
        assert 0 < VULTR_PER_PAGE <= 500


class TestCursorPaginator:
    def test_advances_on_non_empty_next_cursor(self) -> None:
        p = _cursor_paginator()
        p.update_state(_make_response({"instances": [{"id": "a"}], "meta": {"links": {"next": "CURSOR2", "prev": ""}}}))

        assert p.has_next_page is True

        request = Request(method="GET", url="https://api.vultr.com/v2/instances", params={"per_page": VULTR_PER_PAGE})
        p.update_request(request)
        assert request.params["cursor"] == "CURSOR2"
        # The page size must survive alongside the cursor.
        assert request.params["per_page"] == VULTR_PER_PAGE

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"instances": [], "meta": {"links": {"next": "", "prev": ""}}}, id="empty_next_string"),
            pytest.param({"instances": [], "meta": {"links": {}}}, id="missing_next"),
            pytest.param({"instances": []}, id="missing_meta"),
        ],
    )
    def test_stops_when_no_next_cursor(self, body: dict[str, Any]) -> None:
        p = _cursor_paginator()
        p.update_state(_make_response(body))
        assert p.has_next_page is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,schema_name,expected_valid",
        [
            pytest.param(200, None, True, id="200_create"),
            pytest.param(200, "instances", True, id="200_schema"),
            pytest.param(401, None, False, id="401_invalid_token"),
            pytest.param(401, "instances", False, id="401_invalid_token_schema"),
            # A token that 403s on both the account and the data endpoint can never sync, so it is
            # rejected even at create rather than saved as a source that fails every run.
            pytest.param(403, None, False, id="403_create_fully_blocked"),
            pytest.param(403, "instances", False, id="403_rejected_per_schema"),
            pytest.param(500, None, False, id="5xx_unexpected"),
        ],
    )
    def test_status_code_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _make_response(status_code=status_code)

        with patch(f"{VULTR_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("key", schema_name)

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_create_403_accepts_subuser_token_when_data_endpoint_readable(self) -> None:
        # A sub-user token whose ACL blocks /v2/account but permits /v2/instances is usable, so a
        # create-time 403 on the account endpoint is confirmed against a real data endpoint.
        session = MagicMock()
        session.get.side_effect = [_make_response(status_code=403), _make_response(status_code=200)]

        with patch(f"{VULTR_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("key", None)

        assert valid is True
        assert error is None
        assert session.get.call_count == 2
        assert session.get.call_args_list[1][0][0].endswith("/v2/instances")

    def test_sends_bearer_token_to_account_endpoint(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response(status_code=200)

        with patch(f"{VULTR_MODULE}.make_tracked_session", return_value=session):
            validate_credentials("secret-key")

        called_url = session.get.call_args[0][0]
        headers = session.get.call_args.kwargs["headers"]
        assert called_url.endswith("/v2/account")
        assert headers["Authorization"] == "Bearer secret-key"

    def test_network_error_is_not_fatal(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")

        with patch(f"{VULTR_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("key")

        assert valid is False
        assert error is not None


class TestRedactSecrets:
    @pytest.mark.parametrize(
        "row,expected",
        [
            pytest.param(
                {"id": "i-1", "default_password": "hunter2", "label": "web"},
                {"id": "i-1", "label": "web"},
                id="instance_default_password",
            ),
            pytest.param(
                {"id": "db-1", "password": "s3cret", "access_key": "ak", "access_cert": "ac", "host": "h"},
                {"id": "db-1", "host": "h"},
                id="managed_database_credentials",
            ),
            pytest.param(
                # Managed databases nest read-replica objects that carry their own credentials.
                {
                    "id": "db-1",
                    "read_replicas": [{"id": "r-1", "password": "p"}],
                    "ferretdb_credentials": {"password": "p2", "user": "u"},
                },
                {"id": "db-1", "read_replicas": [{"id": "r-1"}], "ferretdb_credentials": {"user": "u"}},
                id="nested_credentials",
            ),
            pytest.param(
                {"id": "b-1", "amount": 10, "description": "invoice"},
                {"id": "b-1", "amount": 10, "description": "invoice"},
                id="no_secrets_untouched",
            ),
        ],
    )
    def test_strips_secret_fields_at_any_depth(self, row: dict[str, Any], expected: dict[str, Any]) -> None:
        assert _redact_secrets(row) == expected


class TestVultrSourceWiring:
    @patch(f"{VULTR_MODULE}.rest_api_resource")
    @patch(f"{VULTR_MODULE}.make_tracked_session")
    def test_source_redacts_rows_and_disables_sample_capture(
        self, mock_session: MagicMock, mock_rest: MagicMock
    ) -> None:
        page = [{"id": "i-1", "default_password": "hunter2", "label": "web"}]
        mock_rest.return_value = Resource(lambda: iter([page]), name="instances", hints={})

        resource = vultr_source(api_key="k", endpoint="instances", team_id=1, job_id="j")
        rows = [row for chunk in resource for row in chunk]

        # Credentials are stripped before rows reach the warehouse table.
        assert rows == [{"id": "i-1", "label": "web"}]
        # Raw responses carry secrets, so the source must opt out of HTTP sample capture.
        assert mock_session.call_args.kwargs["capture"] is False
