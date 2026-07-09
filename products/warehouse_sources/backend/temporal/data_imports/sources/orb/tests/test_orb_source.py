from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb import OrbResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.source import OrbSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> OrbSourceConfig:
    return OrbSourceConfig(api_key="orb-key")


class TestOrbSourceConfig:
    def test_source_type(self) -> None:
        assert OrbSource().source_type == ExternalDataSourceType.ORB

    def test_get_source_config(self) -> None:
        config = OrbSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.ORB
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Shipped behind the unreleased flag while in alpha.
        assert config.unreleasedSource is True

    def test_single_secret_api_key_field(self) -> None:
        fields = OrbSource().get_source_config.fields
        assert fields is not None
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True


class TestGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = OrbSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(list(ENDPOINTS))
    def test_incremental_support_matches_settings(self, endpoint: str) -> None:
        schema = next(s for s in OrbSource().get_schemas(_config(), team_id=1) if s.name == endpoint)
        expected = endpoint in INCREMENTAL_FIELDS
        assert schema.supports_incremental is expected
        assert schema.supports_append is expected
        if expected:
            assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_names_filter(self) -> None:
        schemas = OrbSource().get_schemas(_config(), team_id=1, names=["Customers", "Coupons"])
        assert {s.name for s in schemas} == {"Customers", "Coupons"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.source.validate_orb_credentials")
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = OrbSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestSourceWiring:
    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = OrbSource().get_non_retryable_errors()
        keys = " ".join(errors.keys())
        assert "401" in keys
        assert "403" in keys

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = OrbSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OrbResumeConfig

    def test_canonical_descriptions_present(self) -> None:
        descriptions = OrbSource().get_canonical_descriptions()
        # Keyed by schema name; every documented key must be a real endpoint.
        assert "Customers" in descriptions
        assert set(descriptions.keys()).issubset(set(ENDPOINTS))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.source.orb_source")
    def test_source_for_pipeline_plumbing(self, mock_orb_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Customers"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        OrbSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = cast(dict[str, Any], mock_orb_source.call_args.kwargs)
        assert kwargs["api_key"] == "orb-key"
        assert kwargs["endpoint"] == "Customers"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"
        assert kwargs["resumable_source_manager"] is manager

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.source.orb_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_orb_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "Items"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        OrbSource().source_for_pipeline(_config(), MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_orb_source.call_args.kwargs["db_incremental_field_last_value"] is None
