import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tavus import TavusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source import TavusSource


class TestTavusSource:
    def setup_method(self) -> None:
        self.source = TavusSource()
        self.team_id = 123
        self.config = TavusSourceConfig(api_key="tavus-key")

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Tavus API key"),
            (403, False, "Invalid Tavus API key"),
            (500, False, "Tavus returned HTTP 500"),
            (0, False, "Could not connect to Tavus: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source.check_access")
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "Tavus returned HTTP 500"
            if status == 500
            else ("Could not connect to Tavus: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source.check_access")
    def test_validate_credentials_probes_the_api_key(self, mock_check: mock.MagicMock) -> None:
        # The API key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="replicas")
        mock_check.assert_called_once_with("tavus-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source.tavus_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tavus_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "videos"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_tavus_source.assert_called_once()
        kwargs = mock_tavus_source.call_args.kwargs
        assert kwargs["api_key"] == "tavus-key"
        assert kwargs["endpoint"] == "videos"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Tavus schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
