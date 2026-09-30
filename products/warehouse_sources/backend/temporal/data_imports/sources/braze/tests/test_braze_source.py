import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    BRAZE_DETAILS_ENDPOINTS,
    DATA_SERIES_LOOKBACK_SECONDS,
    ENDPOINTS,
)
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
        # Templates/content blocks expose Braze's server-side `modified_after` filter; every data
        # series is bounded by its own `ending_at`/`length` window.
        assert incremental == {"email_templates", "content_blocks", *BRAZE_DATA_SERIES_ENDPOINTS}
        # A details endpoint takes only its parent id, so there is nothing to sync incrementally.
        for name in BRAZE_DETAILS_ENDPOINTS:
            details = next(schema for schema in schemas if schema.name == name)
            assert details.supports_incremental is False
            assert details.supports_append is False

    def test_data_series_schemas_re_read_a_trailing_window_and_never_append(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name in BRAZE_DATA_SERIES_ENDPOINTS:
            # Braze restates recent days, so appending them would duplicate rather than correct.
            assert schemas[name].supports_append is False
            assert schemas[name].default_incremental_lookback_seconds == DATA_SERIES_LOOKBACK_SECONDS
        assert schemas["email_templates"].supports_append is True
        assert schemas["email_templates"].default_incremental_lookback_seconds is None

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
        mock_validate.assert_called_once_with(
            self.config.api_key, self.config.url, "/campaigns/list?page=0", self.team_id
        )

    @pytest.mark.parametrize(
        "schema_name, expected_probe",
        [
            ("email_templates", "/templates/email/list?page=0"),
            # A workspace series can be probed directly; `length` is all Braze requires.
            ("kpi_dau", "/kpi/dau/data_series?length=1"),
            # A fan-out series needs a parent id we do not have yet, so it probes the list
            # endpoint its fan-out walks — a permission the sync needs either way.
            ("campaign_analytics", "/campaigns/list?page=0"),
            ("canvas_analytics", "/canvas/list?page=0"),
            ("event_analytics", "/events/list?page=0"),
            ("segment_analytics", "/segments/list?page=0"),
            # A details endpoint rejects a request without its parent id, so it probes the same way.
            ("campaign_details", "/campaigns/list?page=0"),
            ("canvas_details", "/canvas/list?page=0"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braze.source.validate_braze_credentials"
    )
    def test_validate_credentials_probes_schema_specific_path(self, mock_validate, schema_name, expected_probe):
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        mock_validate.assert_called_once_with(self.config.api_key, self.config.url, expected_probe, self.team_id)

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
