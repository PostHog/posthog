import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenloop import (
    ZenloopSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source import ZenloopSource


class TestZenloopSource:
    def setup_method(self) -> None:
        self.source = ZenloopSource()
        self.team_id = 123
        self.config = ZenloopSourceConfig(api_token="zenloop-token")

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Zenloop API token"),
            (403, False, "Invalid Zenloop API token"),
            (500, False, "Zenloop returned HTTP 500"),
            (0, False, "Could not connect to Zenloop: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Zenloop returned HTTP 500"
            if status == 500
            else ("Could not connect to Zenloop: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.check_access")
    def test_validate_credentials_probes_the_account_token(self, mock_check: mock.MagicMock) -> None:
        # The API token is account-wide, so validation probes the token, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="properties")
        mock_check.assert_called_once_with("zenloop-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.zenloop_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_zenloop_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "surveys"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zenloop_source.assert_called_once()
        kwargs = mock_zenloop_source.call_args.kwargs
        assert kwargs["api_token"] == "zenloop-token"
        assert kwargs["endpoint"] == "surveys"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Zenloop schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
