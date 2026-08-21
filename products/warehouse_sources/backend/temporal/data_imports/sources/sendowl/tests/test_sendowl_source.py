import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendowl import (
    SendowlSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source import SendowlSource


class TestSendowlSource:
    def setup_method(self) -> None:
        self.source = SendowlSource()
        self.team_id = 123
        self.config = SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret")

    @parameterized.expand(
        [
            ("reachable", 200, True, None),
            ("unauthorized", 401, False, "Invalid SendOwl API credentials"),
            ("forbidden", 403, False, "Invalid SendOwl API credentials"),
            ("server_error", 500, False, "SendOwl returned HTTP 500"),
            ("connection_error", 0, False, "Could not connect to SendOwl: boom"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "SendOwl returned HTTP 500"
            if status == 500
            else ("Could not connect to SendOwl: boom" if status == 0 else None)
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source.check_access"
        ) as mock_check:
            mock_check.return_value = (status, message)
            is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source.check_access")
    def test_validate_credentials_probes_the_credential_pair(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="orders")
        mock_check.assert_called_once_with("sendowl-key", "sendowl-secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source.sendowl_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_sendowl_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_sendowl_source.assert_called_once()
        kwargs = mock_sendowl_source.call_args.kwargs
        assert kwargs["api_key"] == "sendowl-key"
        assert kwargs["api_secret"] == "sendowl-secret"
        assert kwargs["endpoint"] == "products"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SendOwl schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
