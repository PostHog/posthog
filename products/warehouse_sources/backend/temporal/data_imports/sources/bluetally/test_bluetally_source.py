from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally import BluetallyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source import BluetallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key", tenant_id: str | None = None) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.tenant_id = tenant_id
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert BluetallySource().source_type == ExternalDataSourceType.BLUETALLY

    def test_config_is_visible_and_alpha(self) -> None:
        config = BluetallySource().get_source_config
        # A finished source must not be hidden from users.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/bluetally"

    def test_fields(self) -> None:
        fields = {
            f.name: f for f in BluetallySource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)
        }
        assert set(fields) == {"api_key", "tenant_id"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The tenant id is a non-secret, optional connection parameter.
        assert fields["tenant_id"].required is False
        assert fields["tenant_id"].secret is False

    def test_connection_host_fields_force_secret_reentry_on_tenant_change(self) -> None:
        # Changing tenant_id retargets the stored API key, so it must count as a host field.
        assert BluetallySource().connection_host_fields == ["tenant_id"]


class TestGetSchemas:
    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = BluetallySource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # BlueTally has no server-side timestamp filter, so nothing is incremental/append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)
        assert all(s.detected_primary_keys == ["id"] for s in schemas)

    def test_names_filter(self) -> None:
        schemas = BluetallySource().get_schemas(_config(), team_id=1, names=["assets", "employees"])
        assert {s.name for s in schemas} == {"assets", "employees"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert BluetallySource.lists_tables_without_credentials is True
        tables = BluetallySource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assets = next(t for t in tables if t["name"] == "assets")
        assert assets["sync_methods"] == ["Full refresh"]
        assert assets["primary_keys"] == ["id"]


class TestValidateCredentials:
    def test_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=True,
        ) as mocked:
            ok, error = BluetallySource().validate_credentials(_config(tenant_id="7"), team_id=1)
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("key", "7", "/assets")

    def test_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=False,
        ):
            ok, error = BluetallySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None

    def test_probes_specific_endpoint_path(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.validate_bluetally_credentials",
            return_value=True,
        ) as mocked:
            BluetallySource().validate_credentials(_config(), team_id=1, schema_name="employees")
        mocked.assert_called_once_with("key", None, "/employees")


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = BluetallySource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BluetallyResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "licenses"
        inputs.logger = MagicMock()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source.bluetally_source"
        ) as mocked:
            BluetallySource().source_for_pipeline(_config(tenant_id="3"), manager, inputs)
        mocked.assert_called_once_with(
            api_key="key",
            endpoint="licenses",
            logger=inputs.logger,
            resumable_source_manager=manager,
            tenant_id="3",
        )


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://app.bluetallyapp.com/api/v1/assets?limit=1000&offset=0",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://app.bluetallyapp.com/api/v1/employees",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BluetallySource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='app.bluetallyapp.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://app.bluetallyapp.com/api/v1/assets",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://app.bluetallyapp.com/api/v1/assets"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = BluetallySource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_source_exposes_canonical_descriptions(self) -> None:
        assert BluetallySource().get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
