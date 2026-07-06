import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PartnerStackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack import (
    PartnerStackResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source import PartnerStackSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPartnerStackSource:
    def setup_method(self) -> None:
        self.source = PartnerStackSource()
        self.team_id = 123
        self.config = PartnerStackSourceConfig(public_key="pub", private_key="priv")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PARTNERSTACK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "PartnerStack"
        assert config.label == "PartnerStack"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/partnerstack"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["public_key", "private_key"]

    def test_both_key_fields_are_secret_passwords(self) -> None:
        config = self.source.get_source_config
        for name in ("public_key", "private_key"):
            field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == name)
            assert field.type == SourceFieldInputConfigType.PASSWORD
            assert field.secret is True
            assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secret keys; the base URL is hardcoded, so there is no non-secret field an
        # editor could retarget to reuse a preserved key against another account.
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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.partnerstack.com/api/v2/partnerships?limit=250",
            "403 Client Error: Forbidden for url: https://api.partnerstack.com/api/v2/customers?limit=250",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.partnerstack.com/api/v2/partnerships",
            "429 Client Error: Too Many Requests for url: https://api.partnerstack.com/api/v2/customers",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid PartnerStack API keys"),
            (403, False, "Invalid PartnerStack API keys"),
            (500, False, "PartnerStack returned HTTP 500"),
            (0, False, "Could not connect to PartnerStack: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "PartnerStack returned HTTP 500"
            if status == 500
            else ("Could not connect to PartnerStack: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PartnerStackResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source.partnerstack_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "partnerships"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "partnerships"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown PartnerStack schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
