import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source import BitriseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitrise import (
    BitriseSourceConfig,
)


class TestBitriseSource:
    def setup_method(self):
        self.source = BitriseSource()
        self.team_id = 123
        self.config = BitriseSourceConfig(api_token="bitrise-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.bitrise.io/v0.1/apps",
            "403 Client Error: Forbidden for url: https://api.bitrise.io/v0.1/apps/abc123/builds",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.bitrise.io/v0.1/apps",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only builds (and artifacts, through their parent build fan-out) can be filtered
        # server-side via the `after` Unix-timestamp param.
        assert incremental == {"builds", "artifacts"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["builds"].incremental_fields == INCREMENTAL_FIELDS["builds"]
        assert [f["field"] for f in schemas["builds"].incremental_fields] == ["triggered_at"]
        assert [f["field"] for f in schemas["artifacts"].incremental_fields] == ["build_triggered_at"]
        assert schemas["apps"].incremental_fields == []
        # Builds mutate after creation, so append mode is never offered.
        assert all(schema.supports_append is False for schema in schemas.values())

    def test_artifacts_disabled_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["artifacts"].should_sync_default is False
        assert schemas["builds"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds"])
        assert len(schemas) == 1
        assert schemas[0].name == "builds"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Bitrise API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source.validate_bitrise_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)
