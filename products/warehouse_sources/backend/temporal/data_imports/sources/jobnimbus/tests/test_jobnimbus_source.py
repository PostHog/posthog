from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jobnimbus import (
    JobNimbusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source import JobNimbusSource


class TestJobNimbusSource:
    def setup_method(self) -> None:
        self.source = JobNimbusSource()
        self.team_id = 123
        self.config = JobNimbusSourceConfig(api_key="jn-key")

    @parameterized.expand(
        [
            (True, None),
            (False, "Invalid JobNimbus API key"),
            (False, "Could not validate JobNimbus API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source._validate_credentials"
    )
    def test_validate_credentials_delegates(
        self,
        expected_valid: bool,
        expected_message: str | None,
        mock_validate: mock.MagicMock,
    ) -> None:
        # The status→message mapping is exercised against the real function in test_jobnimbus.py;
        # here we only prove the source forwards the account-wide api_key and returns the verdict.
        mock_validate.return_value = (expected_valid, expected_message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message
        mock_validate.assert_called_once_with("jn-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source.jobnimbus_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "jn-key"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
