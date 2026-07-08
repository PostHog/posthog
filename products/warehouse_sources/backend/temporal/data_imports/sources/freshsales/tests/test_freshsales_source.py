from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales import (
    FreshsalesResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source import FreshsalesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshsalesSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(domain: str = "acme", api_key: str = "key") -> FreshsalesSourceConfig:
    return FreshsalesSourceConfig.from_dict({"domain": domain, "api_key": api_key})


def _inputs(schema_name: str = "contacts") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestFreshsalesSource:
    def test_source_type(self) -> None:
        assert FreshsalesSource().source_type == ExternalDataSourceType.FRESHSALES

    def test_connection_host_fields(self) -> None:
        # The API key is sent to a host derived from `domain`, so retargeting it must re-require the key.
        assert FreshsalesSource().connection_host_fields == ["domain"]

    def test_source_config_fields(self) -> None:
        config = FreshsalesSource().get_source_config
        assert config.label == "Freshsales"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"domain", "api_key"}

        domain_field = fields["domain"]
        api_key_field = fields["api_key"]
        assert isinstance(domain_field, SourceFieldInputConfig)
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert domain_field.type == SourceFieldInputConfigType.TEXT
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True

    def test_get_schemas_full_refresh_only(self) -> None:
        schemas = FreshsalesSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Freshsales has no verified server-side timestamp filter, so every endpoint is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = FreshsalesSource().get_schemas(_config(), team_id=1, names=["contacts", "deals"])
        assert {s.name for s in schemas} == {"contacts", "deals"}

    @parameterized.expand(
        [
            ("valid", True, None, None, None, True),
            ("invalid_key", False, "Invalid Freshsales API key", 401, None, False),
            ("forbidden_at_create", False, "no scope", 403, None, True),
            ("forbidden_for_schema", False, "no scope", 403, "contacts", False),
            ("bad_domain", False, "Invalid Freshsales domain", None, None, False),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        check_ok: bool,
        check_error: str | None,
        check_status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source.check_credentials",
            return_value=(check_ok, check_error, check_status),
        ):
            ok, _error = FreshsalesSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_get_non_retryable_errors(self) -> None:
        errors = FreshsalesSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = FreshsalesSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FreshsalesResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        sentinel = object()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source.freshsales_source",
            return_value=sentinel,
        ) as mocked:
            result = FreshsalesSource().source_for_pipeline(_config(), manager, _inputs("deals"))

        assert result is sentinel
        _args, kwargs = mocked.call_args
        assert kwargs["api_key"] == "key"
        assert kwargs["domain"] == "acme"
        assert kwargs["endpoint"] == "deals"
        assert kwargs["resumable_source_manager"] is manager
