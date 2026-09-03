import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source import BillComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billcom import (
    BillComSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source"


class TestBillComSource:
    def setup_method(self) -> None:
        self.source = BillComSource()
        self.team_id = 123
        self.config = BillComSourceConfig(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment="production",
        )

    def test_api_version_is_pinned_to_the_path_the_source_calls(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.resolve_api_version(None) == "v3"

    def test_get_schemas_needs_no_credentials(self) -> None:
        # The endpoint catalog is static, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "BILL sign-in failed: Invalid credentials",
            "401 Client Error: Unauthorized for url: https://gateway.prod.bill.com/connect/v3/bills",
            "403 Client Error: Forbidden for url: https://gateway.prod.bill.com/connect/v3/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://gateway.prod.bill.com/connect/v3/bills",
            "429 Client Error: Too Many Requests for url: https://gateway.prod.bill.com/connect/v3/bills",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    @mock.patch(f"{_MODULE}.bill_com_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bills"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-01T00:00:00.000Z"
        inputs.incremental_field = "updatedTime"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "finance@acme.com"
        assert kwargs["dev_key"] == "dev-key"
        assert kwargs["environment"] == "production"
        assert kwargs["api_version"] == "v3"
        assert kwargs["endpoint"] == "bills"
        assert kwargs["incremental_field"] == "updatedTime"
        assert kwargs["db_incremental_field_last_value"] == "2026-03-01T00:00:00.000Z"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch(f"{_MODULE}.bill_com_source")
    def test_source_for_pipeline_drops_the_cursor_on_a_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "vendors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-01T00:00:00.000Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_every_endpoint_advertises_incremental_fields(self) -> None:
        assert set(INCREMENTAL_FIELDS) == set(ENDPOINTS)
