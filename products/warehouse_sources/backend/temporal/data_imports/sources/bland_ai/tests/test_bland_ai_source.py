from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.source import BlandAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blandai import (
    BlandAISourceConfig,
)


class TestBlandAISource:
    def setup_method(self):
        self.source = BlandAISource()
        self.team_id = 123
        self.config = BlandAISourceConfig(api_key="key")

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs catalog renders.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert [t["name"] for t in documented] == ["calls", "call_transcripts", "pathways"]

    @parameterized.expand(
        [
            # GET /v1/calls has a server-side `start_date` filter, so both call endpoints are incremental.
            ("calls", True, True),
            # Hydrating transcripts costs one request per call, so the table is opt-in.
            ("call_transcripts", True, False),
            # Pathways have no timestamp filters at all — full refresh only.
            ("pathways", False, True),
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
            ("401 Client Error: Unauthorized for url: https://api.bland.ai/v1/calls?from=0&limit=1000",),
            ("401 Client Error: Unauthorized for url: https://api.bland.ai/v1/pathway",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.bland.ai/v1/calls",),
            ("429 Client Error: Too Many Requests for url: https://api.bland.ai/v1/calls",),
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
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.source.validate_bland_ai_credentials"
        ) as mock_validate:
            mock_validate.return_value = mock_return

            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

            assert is_valid is expected_valid
            assert error_message == expected_message
            mock_validate.assert_called_once_with(self.config.api_key)
