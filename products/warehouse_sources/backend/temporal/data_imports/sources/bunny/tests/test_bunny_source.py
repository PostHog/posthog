import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source import BunnySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bunny import BunnySourceConfig


class TestBunnySource:
    def setup_method(self) -> None:
        self.source = BunnySource()
        self.team_id = 123
        self.config = BunnySourceConfig(access_key="bunny-key")

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid bunny.net account API key"),
            ((False, 403), False, "Invalid bunny.net account API key"),
            ((False, 500), False, "bunny.net returned HTTP 500"),
            ((False, None), False, "Could not connect to bunny.net"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_check.return_value = probe_result
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.check_access")
    def test_validate_credentials_probes_the_account_key(self, mock_check: mock.MagicMock) -> None:
        # The account API key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (True, 200)
        self.source.validate_credentials(self.config, self.team_id, schema_name="dns_zones")
        mock_check.assert_called_once_with("bunny-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source.bunny_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bunny_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "pull_zones"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bunny_source.assert_called_once()
        kwargs = mock_bunny_source.call_args.kwargs
        assert kwargs["access_key"] == "bunny-key"
        assert kwargs["endpoint"] == "pull_zones"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown bunny.net schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
