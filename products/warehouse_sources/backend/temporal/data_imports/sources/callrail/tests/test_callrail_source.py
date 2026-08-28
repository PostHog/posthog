import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source import CallRailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.callrail import (
    CallRailSourceConfig,
)


class TestCallRailSource:
    def setup_method(self) -> None:
        self.source = CallRailSource()
        self.team_id = 123
        self.config = CallRailSourceConfig(api_key="key", account_id=None)

    def test_connection_host_fields_includes_account_id(self) -> None:
        # Changing account_id retargets the stored API key, so editing it must require re-entering secrets.
        assert self.source.connection_host_fields == ["account_id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.callrail.com/v3/a/123/calls.json?page=1",
            "403 Client Error: Forbidden for url: https://api.callrail.com/v3/a/123/companies.json",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.callrail.com/v3/a/123/calls.json",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_only_documented_filter_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only calls and form_submissions expose CallRail's server-side `start_date` filter.
        assert incremental == {"calls", "form_submissions"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid CallRail API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.validate_callrail_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.callrail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_callrail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        config = CallRailSourceConfig(api_key="key", account_id="ACC1")
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_callrail_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["account_id"] == "ACC1"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.callrail_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_callrail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_callrail_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.callrail_source")
    def test_source_for_pipeline_blank_account_id_becomes_none(self, mock_callrail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = False
        config = CallRailSourceConfig(api_key="key", account_id="")

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_callrail_source.call_args.kwargs["account_id"] is None
