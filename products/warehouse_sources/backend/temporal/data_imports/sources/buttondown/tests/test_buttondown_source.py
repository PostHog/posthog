import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import BUTTONDOWN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source import ButtondownSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.validate_buttondown_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.buttondown_source"


class TestButtondownSource:
    def setup_method(self) -> None:
        self.source = ButtondownSource()
        self.team_id = 123
        self.config = ButtondownSourceConfig(api_key="bd-key")

    def test_only_endpoints_with_a_server_side_date_filter_advertise_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Advertising incremental on an endpoint with no server-side filter would page the entire
        # history on every run while claiming to be cheap.
        for name, endpoint in BUTTONDOWN_ENDPOINTS.items():
            expected = endpoint.incremental_start_param is not None
            assert schemas[name].supports_incremental is expected
            assert bool(schemas[name].incremental_fields) is expected

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected",
        [
            ((True, 200), None, (True, None)),
            ((False, 401), None, (False, "Invalid Buttondown API key")),
            # A 403 means a real key that can't read one endpoint, so it must not block setup.
            ((False, 403), None, (True, None)),
            ((False, 403), "emails", (False, "Invalid Buttondown API key")),
            ((False, None), None, (False, "Invalid Buttondown API key")),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name) == expected

        mock_validate.assert_called_once_with("bd-key", "2026-04-01")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.buttondown.com/v1/subscribers?page=2",
            "403 Client Error: Forbidden for url: https://api.buttondown.com/v1/emails",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.buttondown.com/v1/subscribers",
        ],
    )
    def test_unrelated_failures_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "emails"
        inputs.team_id = 7
        inputs.job_id = "job"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00Z"
        manager = mock.MagicMock()

        with mock.patch(SOURCE_PATCH) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "bd-key"
        assert kwargs["endpoint"] == "emails"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-03-04T00:00:00Z"
        # An unpinned source must still send the version this code was written against.
        assert kwargs["api_version"] == "2026-04-01"

    def test_source_for_pipeline_honors_a_pinned_api_version(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "emails"
        inputs.api_version = "2025-01-02"

        with mock.patch(SOURCE_PATCH) as mock_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["api_version"] == "2025-01-02"
