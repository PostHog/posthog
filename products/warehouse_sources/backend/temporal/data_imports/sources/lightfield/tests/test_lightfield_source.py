from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightfield import (
    LightfieldSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source import LightfieldSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

CHECK_TOKEN_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source.check_token"


class TestLightfieldSource:
    def setup_method(self):
        self.source = LightfieldSource()
        self.team_id = 123
        self.config = LightfieldSourceConfig(api_key="sk_lf_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LIGHTFIELD

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Lightfield"
        assert config.label == "Lightfield"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/lightfield"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.lightfield.app/v1/accounts?limit=25"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("stripe", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("attio", "403 Client Error: Forbidden for url: https://api.attio.com/v2/self"),
        ]
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, _name, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @parameterized.expand(
        [
            ("known_name", ["accounts"], ["accounts"]),
            ("unknown_name", ["nonexistent"], []),
        ]
    )
    def test_get_schemas_filtered_by_names(self, _name, names, expected):
        schemas = self.source.get_schemas(self.config, self.team_id, names=names)

        assert [schema.name for schema in schemas] == expected

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
