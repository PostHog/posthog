from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightfield import (
    LightfieldSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source import LightfieldSource

CHECK_TOKEN_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source.check_token"


class TestLightfieldSource:
    def setup_method(self):
        self.source = LightfieldSource()
        self.team_id = 123
        self.config = LightfieldSourceConfig(api_key="sk_lf_test")

    @parameterized.expand(
        [
            ("valid_key_no_schema", (True, ["accounts:read"], None), None, True, None),
            ("invalid_key", (False, None, "Invalid Lightfield API key."), None, False, "Invalid Lightfield API key."),
            ("schema_with_granted_scope", (True, ["accounts:read"], None), "accounts", True, None),
            (
                "schema_with_missing_scope",
                (True, ["contacts:read"], None),
                "accounts",
                False,
                "Your Lightfield API key is missing the `accounts:read` scope required to sync accounts.",
            ),
            ("schema_with_unknown_scopes", (True, None, None), "accounts", True, None),
        ]
    )
    @mock.patch(CHECK_TOKEN_PATH)
    def test_validate_credentials(self, _name, token_result, schema_name, expected_valid, expected_error, mock_check):
        mock_check.return_value = token_result

        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert error == expected_error
        mock_check.assert_called_once_with(self.config.api_key, self.source.default_version)

    @mock.patch(CHECK_TOKEN_PATH)
    def test_get_endpoint_permissions_flags_missing_scopes(self, mock_check):
        mock_check.return_value = (True, ["accounts:read", "tasks:read"], None)

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["accounts", "contacts", "tasks"])

        assert permissions == {
            "accounts": None,
            "contacts": "API key is missing the `contacts:read` scope",
            "tasks": None,
        }

    @parameterized.expand(
        [
            ("scopes_unknown", (True, None, None)),
            ("token_invalid", (False, None, "boom")),
        ]
    )
    @mock.patch(CHECK_TOKEN_PATH)
    def test_get_endpoint_permissions_never_blocks_without_scope_list(self, _name, token_result, mock_check):
        mock_check.return_value = token_result

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["accounts", "contacts"])

        assert permissions == {"accounts": None, "contacts": None}

    @mock.patch(CHECK_TOKEN_PATH)
    def test_get_endpoint_permissions_swallows_probe_errors(self, mock_check):
        mock_check.side_effect = Exception("network down")

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["accounts"])

        assert permissions == {"accounts": None}
