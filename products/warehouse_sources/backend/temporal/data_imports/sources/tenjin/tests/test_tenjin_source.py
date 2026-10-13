import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tenjin import TenjinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.source import TenjinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.tenjin import (
    TenjinCredentialsError,
    TenjinRetryableError,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.source"


class TestTenjinSource:
    def setup_method(self) -> None:
        self.source = TenjinSource()
        self.team_id = 123
        self.config = TenjinSourceConfig(api_key="tenjin-token")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static report catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("tenjin-token")

    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_validate_credentials_surfaces_the_specific_rejection(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = TenjinCredentialsError("Tenjin rejected the access token.")

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == "Tenjin rejected the access token."

    @pytest.mark.parametrize(
        "raised",
        [TenjinRetryableError("status=503"), requests.ConnectionError("boom"), requests.ReadTimeout("slow")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_transient_failures_are_not_reported_as_bad_credentials(
        self, mock_validate: mock.MagicMock, raised: Exception
    ) -> None:
        mock_validate.side_effect = raised

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert "temporary rate-limit or network issue" in message

    @mock.patch(f"{_SOURCE_MODULE}.tenjin_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "app_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must not inherit a stale watermark and silently skip history.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
