import json
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield import (
    check_token,
    lightfield_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import LIGHTFIELD_ENDPOINTS


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestLightfieldSourceResponse:
    @parameterized.expand([(name,) for name in LIGHTFIELD_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        source_response = lightfield_source(
            api_key="sk_lf_test",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            api_version="2026-03-01",
        )

        assert source_response.name == endpoint
        assert source_response.primary_keys == ["id"]
        assert source_response.partition_keys == ["createdAt"]
        assert source_response.partition_mode == "datetime"


class TestCheckToken:
    @parameterized.expand(
        [
            (
                "active_key_with_scopes",
                _make_http_response({"active": True, "scopes": ["accounts:read"], "tokenType": "api_key"}),
                (True, ["accounts:read"], None),
            ),
            (
                "active_key_without_scope_list",
                _make_http_response({"active": True}),
                (True, None, None),
            ),
            (
                "inactive_key",
                _make_http_response({"active": False, "scopes": []}),
                (False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."),
            ),
            (
                "unauthorized",
                _make_http_response({"error": "unauthorized"}, status_code=401),
                (False, None, "Invalid Lightfield API key. Check the key and try again."),
            ),
            (
                "server_error",
                _make_http_response({"error": "oops"}, status_code=503),
                (False, None, "Lightfield returned an unexpected status (503) while validating the key."),
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield.make_tracked_session"
    )
    def test_status_mapping(
        self,
        _name: str,
        response: Response,
        expected: tuple[bool, list[str] | None, str | None],
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = response

        assert check_token("sk_lf_test", "2026-03-01") == expected
