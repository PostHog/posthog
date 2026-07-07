import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.finage import source as finage_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.source import FinageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinageSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFinageSource:
    def setup_method(self):
        self.source = FinageSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FINAGE

    def test_source_config_metadata(self):
        config = self.source.get_source_config
        assert config.label == "Finage"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Stays hidden until the connector graduates from alpha.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/finage"

    def test_source_config_fields(self):
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "symbols", "start_date"}

        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

        assert fields["symbols"].required is True
        assert fields["symbols"].secret is False

        # The backfill window is optional and defaults in code.
        assert fields["start_date"].required is False

    def test_get_schemas_full_refresh_only(self):
        schemas = self.source.get_schemas(self._config(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Finage has no server-side updated_after cursor, so every table is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_primary_keys(self):
        schemas = {s.name: s for s in self.source.get_schemas(self._config(), self.team_id)}
        assert schemas["last_quote"].detected_primary_keys == ["symbol"]
        # Fan-out child key includes the symbol so bars from different symbols don't collide.
        assert schemas["aggregates"].detected_primary_keys == ["symbol", "t"]

    def test_get_schemas_names_filter(self):
        schemas = self.source.get_schemas(self._config(), self.team_id, names=["aggregates"])
        assert [s.name for s in schemas] == ["aggregates"]

    def test_lists_tables_without_credentials(self):
        # Static catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {t["name"] for t in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.finage.co.uk",
            "403 Client Error: Forbidden for url: https://api.finage.co.uk",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "status,schema_name,expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # 403 = valid token, plan gap. Accepted at source-create, rejected for a specific schema.
            (403, None, True),
            (403, "aggregates", False),
            (None, None, False),
            (500, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_valid):
        with mock.patch.object(finage_source_module, "validate_finage_credentials", return_value=status):
            valid, message = self.source.validate_credentials(self._config(), self.team_id, schema_name=schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_validate_credentials_rejects_bad_config_before_probing(self):
        # A malformed symbol list must be rejected without ever calling the Finage API.
        with mock.patch.object(finage_source_module, "validate_finage_credentials") as probe:
            valid, message = self.source.validate_credentials(self._config(symbols="not a ticker"), self.team_id)
        assert valid is False
        assert message
        probe.assert_not_called()

    def test_source_for_pipeline_plumbing(self):
        config = self._config(symbols=" aapl , msft ", start_date="2021-06-01")
        inputs = mock.Mock(schema_name="aggregates")
        with mock.patch.object(finage_source_module, "finage_source") as build:
            self.source.source_for_pipeline(config, inputs)

        _args, kwargs = build.call_args
        assert kwargs["endpoint"] == "aggregates"
        assert kwargs["symbols"] == ["AAPL", "MSFT"]
        assert kwargs["start_date"] == "2021-06-01"
        assert kwargs["api_key"] == "secret"

    def test_source_for_pipeline_defaults_start_date(self):
        config = self._config(start_date="")
        inputs = mock.Mock(schema_name="last_quote")
        with mock.patch.object(finage_source_module, "finage_source") as build:
            self.source.source_for_pipeline(config, inputs)

        _args, kwargs = build.call_args
        assert kwargs["start_date"] == finage_source_module.DEFAULT_START_DATE

    def _config(self, symbols: str = "AAPL", start_date: str | None = None) -> FinageSourceConfig:
        return FinageSourceConfig(api_key="secret", symbols=symbols, start_date=start_date)
