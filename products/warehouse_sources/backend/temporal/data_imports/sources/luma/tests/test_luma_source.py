import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.luma import LumaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.source import LumaSource


class TestLumaSource:
    def setup_method(self) -> None:
        self.source = LumaSource()
        self.team_id = 123
        self.config = LumaSourceConfig(api_key="luma-key")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["guests"])
        assert len(schemas) == 1
        assert schemas[0].name == "guests"

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://public-api.luma.com/public/v1/calendar/list-events",),
            ("403 Client Error: Forbidden for url: https://public-api.luma.com/public/v1/event/get-guests",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "500 Server Error: Internal Server Error for url: https://public-api.luma.com/public/v1/calendar/list-events",
            ),
            ("429 Client Error: Too Many Requests for url: https://public-api.luma.com/public/v1/event/get-guests",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.luma.source.luma_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "luma-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Luma schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
