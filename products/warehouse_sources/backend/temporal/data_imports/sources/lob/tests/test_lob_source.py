from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob import LobResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.source import LobSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"letters", "postcards", "checks", "self_mailers"}
FULL_REFRESH_ENDPOINTS = {"addresses", "bank_accounts", "templates", "campaigns"}


def _inputs(schema_name: str = "letters", **overrides) -> SourceInputs:
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
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestLobSourceConfig:
    def test_source_type(self) -> None:
        assert LobSource().source_type == ExternalDataSourceType.LOB

    def test_source_config_metadata(self) -> None:
        config = LobSource().get_source_config
        assert config.label == "Lob"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True

    def test_source_config_has_single_secret_api_key_field(self) -> None:
        fields = LobSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True


class TestLobGetSchemas:
    def test_all_endpoints_present(self) -> None:
        schemas = LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(sorted(INCREMENTAL_ENDPOINTS))
    def test_incremental_endpoints_support_incremental(self, endpoint: str) -> None:
        schema = next(s for s in LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date_created"]

    @parameterized.expand(sorted(FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoints_do_not_support_incremental(self, endpoint: str) -> None:
        schema = next(s for s in LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []
        assert schema.description == "Full refresh only"

    def test_names_filter(self) -> None:
        schemas = LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1, names=["letters"])
        assert [s.name for s in schemas] == ["letters"]


class TestLobValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), None, True),
            ("unauthorized", (False, 401), None, False),
            # A 403 at source-create (no schema) is accepted — the key is real but lacks this scope.
            ("forbidden_at_create", (False, 403), None, True),
            # The same 403 when validating a specific schema is rejected.
            ("forbidden_for_schema", (False, 403), "letters", False),
            ("unknown_error", (False, None), None, False),
        ]
    )
    def test_validate(self, _name: str, probe_result, schema_name, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.source.validate_lob_credentials",
            return_value=probe_result,
        ):
            valid, _error = LobSource().validate_credentials(
                LobSourceConfig(api_key="k"), team_id=1, schema_name=schema_name
            )
        assert valid is expected_valid


class TestLobNonRetryableErrors:
    def test_maps_auth_errors(self) -> None:
        errors = LobSource().get_non_retryable_errors()
        keys = " ".join(errors.keys())
        assert "401" in keys
        assert "403" in keys
        assert all(v for v in errors.values())


class TestLobResumableWiring:
    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = LobSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LobResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        source = LobSource()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.source.lob_source"
        ) as mock_lob_source:
            source.source_for_pipeline(
                LobSourceConfig(api_key="secret"),
                manager,
                _inputs(
                    schema_name="postcards",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2026-01-01",
                ),
            )
        _, kwargs = mock_lob_source.call_args
        assert kwargs["api_key"] == "secret"
        assert kwargs["endpoint"] == "postcards"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        source = LobSource()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.source.lob_source"
        ) as mock_lob_source:
            source.source_for_pipeline(
                LobSourceConfig(api_key="secret"),
                MagicMock(),
                _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01"),
            )
        _, kwargs = mock_lob_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
