from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.linkrunner import (
    LinkrunnerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.source import LinkrunnerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert LinkrunnerSource().source_type == ExternalDataSourceType.LINKRUNNER

    def test_config_advertises_a_single_secret_api_key_field(self) -> None:
        config = LinkrunnerSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ADVERTISING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/linkrunner"
        assert config.iconPath.endswith(".svg")
        assert [f.name for f in config.fields] == ["api_key"]
        api_key = config.fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True


class TestGetSchemas:
    @parameterized.expand(
        [
            # (endpoint, supports_incremental, primary_keys)
            ("campaigns", False, ["display_id"]),
            ("attributed_users", True, ["campaign_display_id", "user_id", "attributed_at"]),
            ("reporting_campaigns", False, ["display_id"]),
        ]
    )
    def test_schema_incremental_and_primary_keys(
        self, endpoint: str, supports_incremental: bool, primary_keys: list[str]
    ) -> None:
        schemas = {s.name: s for s in LinkrunnerSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        # Only attributed-users has a genuine server-side timestamp filter; the rest ship full refresh.
        assert schema.supports_incremental is supports_incremental
        assert schema.detected_primary_keys == primary_keys

    def test_names_filter_restricts_output(self) -> None:
        schemas = LinkrunnerSource().get_schemas(MagicMock(), team_id=1, names=["campaigns"])
        assert [s.name for s in schemas] == ["campaigns"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True lets the public docs render the table catalog with no I/O.
        tables = LinkrunnerSource().get_documented_tables()
        assert {t["name"] for t in tables} == {"campaigns", "attributed_users", "reporting_campaigns"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validation_maps_transport_result(self, _name: str, transport_ok: bool, expected: bool) -> None:
        config = MagicMock(api_key="key")
        with patch.object(source_module, "validate_linkrunner_credentials", return_value=transport_ok):
            ok, error = LinkrunnerSource().validate_credentials(config, team_id=1)
        assert ok is expected
        assert (error is None) is expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.linkrunner.io/api/v1/campaigns",
                True,
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.linkrunner.io/api/v1/attributed-users",
                True,
            ),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.linkrunner.io", False),
            ("timeout", "HTTPSConnectionPool(host='api.linkrunner.io', port=443): Read timed out.", False),
        ]
    )
    def test_only_credential_errors_are_non_retryable(self, _name: str, observed: str, expected: bool) -> None:
        non_retryable = LinkrunnerSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable) is expected


class TestPipelineWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = LinkrunnerSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LinkrunnerResumeConfig

    def test_source_for_pipeline_plumbs_incremental_inputs(self) -> None:
        config = MagicMock(api_key="key")
        inputs = MagicMock(
            schema_name="attributed_users",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="attributed_at",
        )
        manager = MagicMock()
        with patch.object(source_module, "linkrunner_source") as mock_source:
            LinkrunnerSource().source_for_pipeline(config, manager, inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "attributed_users"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        config = MagicMock(api_key="key")
        inputs = MagicMock(
            schema_name="campaigns",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field=None,
        )
        with patch.object(source_module, "linkrunner_source") as mock_source:
            LinkrunnerSource().source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


def test_registered_in_source_registry() -> None:
    from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry

    sources = SourceRegistry.get_all_sources()
    assert ExternalDataSourceType.LINKRUNNER in sources
    assert sources[ExternalDataSourceType.LINKRUNNER].source_type == ExternalDataSourceType.LINKRUNNER
