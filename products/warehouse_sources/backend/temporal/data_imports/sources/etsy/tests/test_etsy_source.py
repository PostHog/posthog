from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy import EtsyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import ENDPOINTS, ETSY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.source import EtsySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.etsy import EtsySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if not cfg.incremental_fields]


def _config(shop_id: Optional[str] = None) -> EtsySourceConfig:
    return EtsySourceConfig(api_key="key", refresh_token="refresh", shop_id=shop_id)


class TestEtsySourceClass:
    def test_source_type(self) -> None:
        assert EtsySource().source_type == ExternalDataSourceType.ETSY

    def test_source_config(self) -> None:
        config = EtsySource().get_source_config

        assert config.label == "Etsy"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/etsy"
        assert config.iconPath == "/static/services/etsy.png"
        # A hidden source cannot be connected — a finished source must stay visible.
        assert config.unreleasedSource is None

    def test_source_fields(self) -> None:
        fields = EtsySource().get_source_config.fields
        assert [f.name for f in fields] == ["api_key", "refresh_token", "shop_id"]

    @parameterized.expand([("api_key", True, True), ("refresh_token", True, True), ("shop_id", False, False)])
    def test_credential_fields_are_secret_and_shop_id_is_optional(
        self, name: str, expected_secret: bool, expected_required: bool
    ) -> None:
        field = next(f for f in EtsySource().get_source_config.fields if f.name == name)

        assert isinstance(field, SourceFieldInputConfig)
        assert field.secret is expected_secret
        assert field.required is expected_required

    def test_shop_id_is_a_connection_host_field(self) -> None:
        # shop_id steers where the stored token is sent, so changing it must force credential re-entry.
        assert EtsySource().connection_host_fields == ["shop_id"]

    def test_api_version_metadata(self) -> None:
        assert EtsySource.supported_versions == ("v3",)
        assert EtsySource.default_version == "v3"
        assert EtsySource.api_docs_url is not None
        assert EtsySource.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list must render.
        assert EtsySource.lists_tables_without_credentials is True
        assert {table["name"] for table in EtsySource().get_documented_tables()} == set(ENDPOINTS)

    @parameterized.expand([("401",), ("403",), ("no shop",)])
    def test_non_retryable_errors_cover_permanent_failures(self, fragment: str) -> None:
        assert any(fragment in key for key in EtsySource().get_non_retryable_errors())

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = EtsySource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand([(name,) for name in _INCREMENTAL_ENDPOINTS])
    def test_incremental_endpoints_support_incremental(self, endpoint: str) -> None:
        schema = EtsySource().get_schemas(_config(), team_id=1, names=[endpoint])[0]

        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == [
            f["field"] for f in ETSY_ENDPOINTS[endpoint].incremental_fields
        ]

    @parameterized.expand([(name,) for name in _FULL_REFRESH_ENDPOINTS])
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint: str) -> None:
        schema = EtsySource().get_schemas(_config(), team_id=1, names=[endpoint])[0]

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    def test_get_schemas_name_filter(self) -> None:
        schemas = EtsySource().get_schemas(_config(), team_id=1, names=["receipts"])
        assert [s.name for s in schemas] == ["receipts"]

    @parameterized.expand([(True, None), (False, "Bad credentials")])
    def test_validate_credentials_passes_through(self, ok: bool, error: Optional[str]) -> None:
        with patch.object(source_module, "validate_etsy_credentials", return_value=(ok, error)) as mock_validate:
            assert EtsySource().validate_credentials(_config("42"), team_id=1) == (ok, error)

        assert mock_validate.call_args.args == ("key", "refresh", "42")

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = EtsySource().get_resumable_source_manager(MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EtsyResumeConfig

    @patch.object(source_module, "etsy_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_etsy_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "receipts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1_700_000_000
        inputs.incremental_field = "updated_timestamp"
        manager = MagicMock()

        EtsySource().source_for_pipeline(_config("42"), manager, inputs)

        kwargs = mock_etsy_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["refresh_token"] == "refresh"
        assert kwargs["shop_id"] == "42"
        assert kwargs["endpoint"] == "receipts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1_700_000_000
        assert kwargs["incremental_field"] == "updated_timestamp"

    @patch.object(source_module, "etsy_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_etsy_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "listings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1_700_000_000

        EtsySource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mock_etsy_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_match_endpoints(self) -> None:
        descriptions = EtsySource().get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
