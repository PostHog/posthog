import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_DATA_SERIES_ENDPOINTS,
    DATA_SERIES_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.source import BrazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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

    def test_data_series_schemas_re_read_a_trailing_window_and_never_append(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name in BRAZE_DATA_SERIES_ENDPOINTS:
            # Braze restates recent days, so appending them would duplicate rather than correct.
            assert schemas[name].supports_append is False
            assert schemas[name].default_incremental_lookback_seconds == DATA_SERIES_LOOKBACK_SECONDS
        assert schemas["email_templates"].supports_append is True
        assert schemas["email_templates"].default_incremental_lookback_seconds is None

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status, expected_valid, expected_message):
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.url for request in network.requests_log] == [f"{BASE_URL}/campaigns/list?page=0"]
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    def test_validate_credentials_rejects_unknown_schema(self):
        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name="does_not_exist"
            )

        assert is_valid is False
        assert "does_not_exist" in (error_message or "")
        # Never probes the API for an unknown schema.
        assert network.requests_log == []

    def test_validate_credentials_accepts_missing_scope_at_source_create(self):
        # A scoped key may lack the probe endpoint's permission at create time — accepted.
        with scripted_network([ScriptedResponse(status=403)]):
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    def test_validate_credentials_enforces_scope_for_specific_schema(self):
        with scripted_network([ScriptedResponse(status=403)]) as network:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name="email_templates"
            )

        assert is_valid is False
        assert error_message == "Your Braze API key does not have permission for this endpoint"
        assert [request.url for request in network.requests_log] == [f"{BASE_URL}/templates/email/list?page=0"]
