import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SendowlSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl import SendowlResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source import SendowlSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSendowlSource:
    def setup_method(self) -> None:
        self.source = SendowlSource()
        self.team_id = 123
        self.config = SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SENDOWL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Sendowl"
        assert config.label == "Sendowl"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sendowl"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret"]

    @parameterized.expand([("api_key",), ("api_secret",)])
    def test_credential_fields_are_secret_passwords(self, field_name: str) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secrets; the base URL is hardcoded and the account is implicit in the key
        # pair. There is no non-secret field that retargets where the credentials are sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://www.sendowl.com/api/v1/products?page=1&per_page=50",),
            ("403 Client Error: Forbidden for url: https://www.sendowl.com/api/v1_3/orders?page=2&per_page=50",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://www.sendowl.com/api/v1/products",),
            ("HTTPSConnectionPool(host='www.sendowl.com', port=443): Read timed out.",),
            ("429 Client Error: Too Many Requests for url: https://www.sendowl.com/api/v1_3/orders",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

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

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SendowlResumeConfig

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
