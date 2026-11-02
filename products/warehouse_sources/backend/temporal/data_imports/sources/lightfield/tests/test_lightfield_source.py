from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightfield import (
    LightfieldSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source import LightfieldSource


class TestLightfieldSource:
    def setup_method(self) -> None:
        self.source = LightfieldSource()
        self.team_id = 123
        self.config = LightfieldSourceConfig(api_key="sk_lf_test")

    @parameterized.expand(
        [
            ("stripe", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("attio", "403 Client Error: Forbidden for url: https://api.attio.com/v2/self"),
        ]
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, _name, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_vendor_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("valid_key_no_schema", 200, {"active": True, "scopes": ["accounts:read"]}, None, True, None),
            (
                "invalid_key",
                401,
                {"error": "unauthorized"},
                None,
                False,
                "Invalid Lightfield API key. Check the key and try again.",
            ),
            ("schema_with_granted_scope", 200, {"active": True, "scopes": ["accounts:read"]}, "accounts", True, None),
            (
                "schema_with_missing_scope",
                200,
                {"active": True, "scopes": ["contacts:read"]},
                "accounts",
                False,
                "Your Lightfield API key is missing the `accounts:read` scope required to sync accounts.",
            ),
            ("schema_with_unknown_scopes", 200, {"active": True}, "accounts", True, None),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        body: dict[str, Any],
        schema_name: str | None,
        expected_valid: bool,
        expected_error: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert error == expected_error
        assert {request.path for request in network.requests_log} == {"/v1/auth/validate"}
        assert all(
            request.headers["lightfield-version"] == self.source.default_version for request in network.requests_log
        )

    def test_get_endpoint_permissions_flags_missing_scopes(self) -> None:
        with scripted_network([ScriptedResponse(json={"active": True, "scopes": ["accounts:read", "tasks:read"]})]):
            permissions = self.source.get_endpoint_permissions(
                self.config, self.team_id, ["accounts", "contacts", "tasks"]
            )

        assert permissions == {
            "accounts": None,
            "contacts": "API key is missing the `contacts:read` scope",
            "tasks": None,
        }

    @parameterized.expand(
        [
            ("scopes_unknown", 200, {"active": True}),
            ("token_invalid", 401, {"error": "unauthorized"}),
        ]
    )
    def test_get_endpoint_permissions_never_blocks_without_scope_list(
        self, _name: str, status: int, body: dict[str, Any]
    ) -> None:
        with scripted_network([ScriptedResponse(status=status, json=body)]):
            permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["accounts", "contacts"])

        assert permissions == {"accounts": None, "contacts": None}

    def test_get_endpoint_permissions_swallows_probe_errors(self) -> None:
        with scripted_network(always(ConnectionError("network down"))):
            permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["accounts"])

        assert permissions == {"accounts": None}

    @parameterized.expand(
        [
            ("no_pin_uses_default", None, "2026-03-01"),
            ("pin_honored_verbatim", "2027-01-01", "2027-01-01"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source.lightfield_source")
    def test_source_for_pipeline_resolves_api_version(self, _name, pinned, expected_version, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.team_id = self.team_id
        inputs.job_id = "job_1"
        inputs.api_version = pinned

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            api_key=self.config.api_key,
            endpoint="accounts",
            team_id=self.team_id,
            job_id="job_1",
            api_version=expected_version,
        )
