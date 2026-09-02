from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vapi import VapiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.settings import (
    ENDPOINTS,
    VAPI_VERSION_V1,
    VAPI_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source import VapiSource

# Endpoints whose Vapi list action exposes a server-side timestamp filter usable with the
# endpoint's ordering guarantees; the rest are full refresh only.
_INCREMENTAL_ENDPOINTS = {"calls", "chats", "sessions"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestVapiSource:
    def setup_method(self):
        self.source = VapiSource()
        self.team_id = 123
        self.config = VapiSourceConfig(api_key="key")

    def test_declares_v1_and_v2_with_v2_default(self):
        # New sources are stamped v2; v1 stays declared so existing pinned rows keep their path.
        assert self.source.supported_versions == (VAPI_VERSION_V1, VAPI_VERSION_V2)
        assert self.source.default_version == VAPI_VERSION_V2

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.vapi.ai/call?limit=100",
            "403 Client Error: Forbidden for url: https://api.vapi.ai/assistant?limit=100",
            "400 Client Error: Bad Request for url: https://api.vapi.ai/v2/phone-number?limit=100&page=1&sortOrder=ASC&sortBy=createdAt",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            "429 Client Error: Too Many Requests for url: https://api.vapi.ai/call",
            "500 Server Error: Internal Server Error for url: https://api.vapi.ai/call",
            "HTTPSConnectionPool(host='api.vapi.ai', port=443): Read timed out.",
            # A 400 on a different endpoint must stay retryable — only the known-bad v2
            # phone-number path is non-retryable, not every 400 from api.vapi.ai.
            "400 Client Error: Bad Request for url: https://api.vapi.ai/call?limit=100",
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert "createdAt" in [f["field"] for f in schemas[name].incremental_fields]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_calls_offers_updated_at_incremental_field(self):
        # updatedAt re-syncs calls whose analysis/artifacts land after the call ends.
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [f["field"] for f in schemas[0].incremental_fields] == ["createdAt", "updatedAt"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [s.name for s in schemas] == ["calls"]

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid Vapi API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source.validate_vapi_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source.vapi_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_vapi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.api_version = VAPI_VERSION_V1
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.db_incremental_field_earliest_value = "2025-01-01T00:00:00.000Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_vapi_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["db_incremental_field_earliest_value"] == "2025-01-01T00:00:00.000Z"

    @parameterized.expand(
        [
            ("no_pin_defaults_to_v2", None, VAPI_VERSION_V2),
            ("v1_pin_preserved", VAPI_VERSION_V1, VAPI_VERSION_V1),
            ("v2_pin_preserved", VAPI_VERSION_V2, VAPI_VERSION_V2),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source.vapi_source")
    def test_source_for_pipeline_resolves_api_version(self, _name, pin, expected, mock_vapi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "phone_numbers"
        inputs.api_version = pin
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_vapi_source.call_args.kwargs["api_version"] == expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source.vapi_source")
    def test_source_for_pipeline_omits_cursors_when_not_incremental(self, mock_vapi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "assistants"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.db_incremental_field_earliest_value = "2025-01-01T00:00:00.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_vapi_source.call_args.kwargs["db_incremental_field_last_value"] is None
        assert mock_vapi_source.call_args.kwargs["db_incremental_field_earliest_value"] is None
