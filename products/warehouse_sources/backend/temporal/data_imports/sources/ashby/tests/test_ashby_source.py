import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source import AshbySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ashby import AshbySourceConfig


class TestAshbySource:
    def setup_method(self) -> None:
        self.source = AshbySource()
        self.team_id = 123
        self.config = AshbySourceConfig(api_key="ashby-key")

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Ashby has no timestamp-watermark incremental, so every schema is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Ashby API authentication or permission error for path candidate.list",
            "403 Client Error: Ashby API authentication or permission error for path job.list",
            "Ashby API authentication or permission error for path candidate.list: Missing permission",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (401, None, False, "Invalid Ashby API key"),
            # 403 at source-create is accepted (key may be scoped to a subset of endpoints).
            (403, None, True, None),
            # 403 for a specific schema is rejected.
            (403, "candidates", False, "Your Ashby API key does not have permission to read 'candidates'"),
            (400, None, False, "boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_check.return_value = (status, "boom")
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source.check_access")
    def test_validate_credentials_probes_schema_path_when_given(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="candidates")
        mock_check.assert_called_once_with("ashby-key", "candidate.list")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source.check_access")
    def test_validate_credentials_uses_default_probe_without_schema(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id)
        mock_check.assert_called_once_with("ashby-key", "department.list")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source.check_access")
    def test_validate_credentials_rejects_unknown_schema_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown Ashby schema 'not_a_table'"
        mock_check.assert_not_called()
