from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import error_message_matches
from products.warehouse_sources.sources.vapi._config import VapiSourceConfig
from products.warehouse_sources.sources.vapi.settings import VAPI_VERSION_V1, VAPI_VERSION_V2
from products.warehouse_sources.sources.vapi.source import VapiSource


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
            "400 Client Error: Bad Request for url: https://api.vapi.ai/v2/phone-number?limit=100&page=1&sortOrder=ASC&sortBy=createdAt",
            "400 Client Error: Bad Request for url: https://api.vapi.ai/chat?createdAtGt=2026-09-11T12%3A24%3A53.890Z&limit=100&page=1&sortOrder=ASC&sortBy=createdAt",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            # A 400 on a different endpoint must stay retryable — only the known-bad v2
            # phone-number and chat paths are non-retryable, not every 400 from api.vapi.ai.
            "400 Client Error: Bad Request for url: https://api.vapi.ai/call?limit=100",
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            (
                "exhausted_5xx",
                "Vapi API error (retryable): status=503, url=https://api.vapi.ai/eval/simulation/run?limit=100&page=1",
                True,
            ),
            (
                "exhausted_429",
                "Vapi API error (retryable): status=429, url=https://api.vapi.ai/call?limit=100",
                True,
            ),
            (
                "read_timeout",
                "HTTPSConnectionPool(host='api.vapi.ai', port=443): Read timed out. (read timeout=60)",
                True,
            ),
            (
                "connection_error",
                "HTTPSConnectionPool(host='api.vapi.ai', port=443): Max retries exceeded with url: /call?limit=100 "
                "(Caused by NewConnectionError('Failed to establish a new connection: [Errno 111] Connection refused'))",
                True,
            ),
            # Client errors are not transient: they must stay reported.
            ("bad_request", "400 Client Error: Bad Request for url: https://api.vapi.ai/call?limit=100", False),
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vapi.ai/call?limit=100", False),
            # A timeout against another host is not Vapi's to classify.
            (
                "other_host_timeout",
                "HTTPSConnectionPool(host='api.example.com', port=443): Read timed out. (read timeout=60)",
                False,
            ),
        ]
    )
    def test_retryable_errors_cover_exhausted_transient_failures(self, _name, error_msg, expected):
        assert error_message_matches(error_msg, self.source.get_retryable_errors()) is expected

    def test_calls_offers_updated_at_incremental_field(self):
        # updatedAt re-syncs calls whose analysis/artifacts land after the call ends.
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [f["field"] for f in schemas[0].incremental_fields] == ["createdAt", "updatedAt"]

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid Vapi API key"),
        ]
    )
    @mock.patch("products.warehouse_sources.sources.vapi.source.validate_vapi_credentials")
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    @mock.patch("products.warehouse_sources.sources.vapi.source.vapi_source")
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
    @mock.patch("products.warehouse_sources.sources.vapi.source.vapi_source")
    def test_source_for_pipeline_resolves_api_version(self, _name, pin, expected, mock_vapi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "phone_numbers"
        inputs.api_version = pin
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_vapi_source.call_args.kwargs["api_version"] == expected
