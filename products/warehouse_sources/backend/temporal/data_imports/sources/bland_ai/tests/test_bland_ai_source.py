from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.source import BlandAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blandai import (
    BlandAISourceConfig,
)


class TestBlandAISource:
    def setup_method(self):
        self.source = BlandAISource()
        self.team_id = 123
        self.config = BlandAISourceConfig(api_key="key")

    @parameterized.expand(
        [
            # GET /v1/calls has a server-side `start_date` filter, so both call endpoints are incremental.
            ("calls", True, True),
            # Hydrating transcripts costs one request per call, so the table is opt-in.
            ("call_transcripts", True, False),
            # Pathways have no timestamp filters at all — full refresh only.
            ("pathways", False, True),
            # GET /v1/sms/conversations filters on `created_at` with a `gte` operator.
            ("sms_conversations", True, True),
            # Hydrating messages costs one request per conversation, so the table is opt-in.
            ("sms_messages", True, False),
            # Account-level lookups with no timestamp filters — full refresh only.
            ("inbound_numbers", False, True),
            ("personas", False, True),
            ("voices", False, True),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint, supports_incremental, should_sync_default):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)

        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        assert schema.should_sync_default is should_sync_default
        assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
        ]
    )
    def test_non_retryable_errors_does_not_match_transient_or_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Bland AI API key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        status = 200 if mock_return else 401
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].headers["authorization"] == self.config.api_key
