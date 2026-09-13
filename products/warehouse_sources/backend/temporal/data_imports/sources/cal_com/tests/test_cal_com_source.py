import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source import CalComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig


class TestCalComSource:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.team_id = 123
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")

    def test_region_field_defaults_to_us(self) -> None:
        # Every connection made before this field existed talks to the US host, so the default must
        # stay "us" or those syncs start pointing at the EU host.
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert field.defaultValue == "us"
        assert {option.value for option in field.options} == {"us", "eu"}

    def test_no_connection_host_fields(self) -> None:
        # `region` only picks between two fixed Cal.com hosts, so it can't be used to retarget a
        # preserved key at a server the editor controls.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.cal.com/v2/bookings?limit=250",),
            ("403 Client Error: Forbidden for url: https://api.cal.com/v2/me",),
            ("401 Client Error: Unauthorized for url: https://api.cal.eu/v2/bookings?limit=250",),
            ("403 Client Error: Forbidden for url: https://api.cal.eu/v2/me",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.cal.com/v2/bookings",),
            ("429 Client Error: Too Many Requests for url: https://api.cal.com/v2/teams",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source.cal_com_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "cal_live_key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["region"] == "us"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source.cal_com_source")
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Cal.com schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
