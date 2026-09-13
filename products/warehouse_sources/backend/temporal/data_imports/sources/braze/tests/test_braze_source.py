import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.source import BrazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braze import BrazeSourceConfig

BASE_URL = "https://rest.iad-01.braze.com"


class TestBrazeSource:
    def setup_method(self):
        self.source = BrazeSource()
        self.team_id = 123
        self.config = BrazeSourceConfig(api_key="key", url=BASE_URL)

    def test_url_is_a_connection_host_field(self):
        # The API key is sent to the host in `url`, so retargeting it must re-require the secret.
        assert self.source.connection_host_fields == ["url"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://rest.iad-01.braze.com/campaigns/list?page=0",
            "403 Client Error: Forbidden for url: https://rest.iad-01.braze.com/events/list?page=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://rest.iad-01.braze.com/campaigns/list",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only templates/content blocks expose Braze's server-side `modified_after` filter.
        assert incremental == {"email_templates", "content_blocks"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Braze API key"), False, "Invalid Braze API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.url, "/campaigns/list", self.team_id)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_probes_schema_specific_path(self, mock_validate):
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name="email_templates")

        mock_validate.assert_called_once_with(
            self.config.api_key, self.config.url, "/templates/email/list", self.team_id
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_rejects_unknown_schema(self, mock_validate):
        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="does_not_exist"
        )

        assert is_valid is False
        assert "does_not_exist" in (error_message or "")
        # Never probes the API for an unknown schema.
        mock_validate.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_accepts_missing_scope_at_source_create(self, mock_validate):
        # A scoped key may lack the probe endpoint's permission at create time — accepted.
        mock_validate.return_value = (False, "Your Braze API key does not have permission for this endpoint")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_enforces_scope_for_specific_schema(self, mock_validate):
        mock_validate.return_value = (False, "Your Braze API key does not have permission for this endpoint")

        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="email_templates"
        )

        assert is_valid is False
        assert error_message == "Your Braze API key does not have permission for this endpoint"
