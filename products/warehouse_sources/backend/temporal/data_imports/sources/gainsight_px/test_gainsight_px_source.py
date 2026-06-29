from unittest.mock import patch

import structlog
from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source import GainsightPxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GainsightPxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = structlog.get_logger()


def _config() -> GainsightPxSourceConfig:
    return GainsightPxSource().parse_config({"region": "eu", "api_key": "abc"})


def _inputs(schema_name: str = "accounts", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": LOGGER,
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSourceType:
    def test_source_type(self) -> None:
        assert GainsightPxSource().source_type == ExternalDataSourceType.GAINSIGHTPX


class TestSourceConfig:
    def test_basic_metadata(self) -> None:
        config = GainsightPxSource().get_source_config
        assert config.label == "Gainsight PX"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        # The source must ship visible (not hidden behind `unreleasedSource`) — that's the whole point
        # of finishing it.
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"
        assert config.docsUrl
        assert GainsightPxSource().lists_tables_without_credentials is True

    def test_fields(self) -> None:
        fields = {f.name: f for f in GainsightPxSource().get_source_config.fields}
        assert set(fields) == {"region", "api_key"}

        region = fields["region"]
        assert isinstance(region, SourceFieldSelectConfig)
        assert {o.value for o in region.options} == {"us", "eu", "us2"}
        assert region.defaultValue == "us"

        api_key = fields["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        # Must be flagged secret so it's stored encrypted and never echoed back.
        assert api_key.secret is True


class TestConnectionHostFields:
    def test_region_requires_secret_re_entry(self) -> None:
        # Security invariant: retargeting the host the stored key is sent to must force key re-entry.
        assert GainsightPxSource().connection_host_fields == ["region"]


class TestGetSchemas:
    def test_all_endpoints_present(self) -> None:
        schemas = {s.name for s in GainsightPxSource().get_schemas(_config(), team_id=1)}
        assert schemas == set(ENDPOINTS)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_endpoint_is_full_refresh(self, endpoint: str) -> None:
        # PX exposes no server-side modified-since filter, so advertising incremental here would be a
        # false promise that re-fetches everything each run.
        schemas = {s.name: s for s in GainsightPxSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].detected_primary_keys == ["id"]

    def test_filter_by_names(self) -> None:
        schemas = GainsightPxSource().get_schemas(_config(), team_id=1, names=["users"])
        assert [s.name for s in schemas] == ["users"]


class TestValidateCredentials:
    @parameterized.expand([("ok", True), ("bad", False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool) -> None:
        with patch.object(
            source_module, "validate_gainsight_px_credentials", return_value=transport_result
        ) as mock_validate:
            ok, error = GainsightPxSource().validate_credentials(_config(), team_id=1)
        assert ok is transport_result
        assert (error is None) is transport_result
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["api_key"] == "abc"


class TestNonRetryableErrors:
    def test_auth_errors_present(self) -> None:
        errors = GainsightPxSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestSourceForPipeline:
    def test_plumbs_arguments(self) -> None:
        with patch.object(source_module, "gainsight_px_source") as mock_source:
            GainsightPxSource().source_for_pipeline(_config(), _inputs(schema_name="users"))
        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["api_key"] == "abc"
        assert kwargs["endpoint"] == "users"


class TestDocumentedTables:
    def test_lists_every_endpoint_without_credentials(self) -> None:
        # Exercises the public-docs path (placeholder config, no I/O) that `lists_tables_without_credentials`
        # turns on.
        tables = GainsightPxSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestCanonicalDescriptions:
    def test_keyed_by_endpoint_name(self) -> None:
        canon = GainsightPxSource().get_canonical_descriptions()
        # Descriptions only apply when keyed by the exact schema name `get_schemas` returns.
        assert set(canon) == set(ENDPOINTS)
        assert all(entry.get("description") for entry in canon.values())
