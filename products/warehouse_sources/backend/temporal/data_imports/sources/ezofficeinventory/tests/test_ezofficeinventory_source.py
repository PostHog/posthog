from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory import (
    EZOfficeInventoryResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source import (
    EZOfficeInventorySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    EZOfficeInventorySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source"


def _config() -> EZOfficeInventorySourceConfig:
    return cast(EZOfficeInventorySourceConfig, EZOfficeInventorySourceConfig(subdomain="acme", api_key="tok"))


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert EZOfficeInventorySource().source_type == ExternalDataSourceType.EZOFFICEINVENTORY

    def test_get_source_config_fields(self) -> None:
        config = EZOfficeInventorySource().get_source_config
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in config.fields}
        assert set(fields) == {"subdomain", "api_key"}
        # The token is the only secret; the subdomain is a plain connection host field.
        assert fields["api_key"].secret is True
        assert fields["subdomain"].secret is False
        assert fields["api_key"].required is True
        assert fields["subdomain"].required is True

    def test_get_source_config_metadata(self) -> None:
        config = EZOfficeInventorySource().get_source_config
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ezofficeinventory"

    def test_connection_host_fields_include_subdomain(self) -> None:
        # Retargeting the subdomain must re-require the stored token.
        assert EZOfficeInventorySource().connection_host_fields == ["subdomain"]


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh(self) -> None:
        schemas = EZOfficeInventorySource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # EZOfficeInventory exposes no server-side cursor — every table is full refresh.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_primary_keys_are_endpoint_specific(self) -> None:
        schemas = {s.name: s for s in EZOfficeInventorySource().get_schemas(_config(), team_id=1)}
        assert schemas["assets"].detected_primary_keys == ["identifier"]
        assert schemas["members"].detected_primary_keys == ["id"]

    def test_names_filter(self) -> None:
        schemas = EZOfficeInventorySource().get_schemas(_config(), team_id=1, names=["assets", "members"])
        assert {s.name for s in schemas} == {"assets", "members"}

    def test_documented_tables_render_without_credentials(self) -> None:
        source = EZOfficeInventorySource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        # Curated descriptions flow through from canonical_descriptions.py.
        assets = next(t for t in tables if t["name"] == "assets")
        assert assets["description"]
        assert assets["sync_methods"] == ["Full refresh"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("transport_result", "expected_ok"),
        [((True, None), True), ((False, None), False)],
    )
    def test_delegates_to_transport(self, transport_result: tuple[bool, str | None], expected_ok: bool) -> None:
        with patch(f"{_MODULE}.validate_ezofficeinventory_credentials", return_value=transport_result) as mocked:
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        mocked.assert_called_once_with("tok", "acme")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_surfaces_transport_error_message(self) -> None:
        with patch(
            f"{_MODULE}.validate_ezofficeinventory_credentials",
            return_value=(False, "EZOfficeInventory rate limit reached while validating credentials."),
        ):
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "EZOfficeInventory rate limit reached while validating credentials."


class TestNonRetryableErrors:
    def test_auth_errors_are_non_retryable(self) -> None:
        errors = EZOfficeInventorySource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = EZOfficeInventorySource().get_resumable_source_manager(inputs)
        assert manager._data_class is EZOfficeInventoryResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "members"
        inputs.logger = MagicMock()
        manager = MagicMock()

        with patch(f"{_MODULE}.ezofficeinventory_source") as mocked:
            EZOfficeInventorySource().source_for_pipeline(_config(), manager, inputs)

        mocked.assert_called_once_with(
            api_key="tok",
            subdomain="acme",
            endpoint="members",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
