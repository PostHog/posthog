from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    ENDPOINTS,
    TRUSTPILOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source import TrustPilotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    TrustpilotResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source"


def _config() -> TrustPilotSourceConfig:
    return TrustPilotSourceConfig(api_key="tp-secret", business_unit_id="46d76a9f0000640005034a5f")


def _input_fields(source: TrustPilotSource) -> dict[str, SourceFieldInputConfig]:
    return {
        field.name: field
        for field in source.get_source_config.fields or []
        if isinstance(field, SourceFieldInputConfig)
    }


class TestTrustPilotSource:
    def test_source_type(self) -> None:
        assert TrustPilotSource().source_type == ExternalDataSourceType.TRUSTPILOT

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        config = TrustPilotSource().get_source_config

        # `unreleasedSource` hides a source from users entirely; a finished source must not set it.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.docsUrl is not None

    @parameterized.expand(
        [
            ("api_key", SourceFieldInputConfigType.PASSWORD, True, True),
            ("business_unit_id", SourceFieldInputConfigType.TEXT, True, False),
        ]
    )
    def test_credential_fields(
        self, name: str, field_type: SourceFieldInputConfigType, required: bool, secret: bool
    ) -> None:
        field = _input_fields(TrustPilotSource())[name]

        assert field.type == field_type
        assert field.required is required
        assert field.secret is secret

    def test_get_schemas_returns_the_whole_catalog_with_its_keys(self) -> None:
        schemas = TrustPilotSource().get_schemas(_config(), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        for schema in schemas:
            assert schema.detected_primary_keys == TRUSTPILOT_ENDPOINTS[schema.name].primary_keys

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = TrustPilotSource().get_schemas(_config(), team_id=1, names=["service_reviews"])

        assert [schema.name for schema in schemas] == ["service_reviews"]

    def test_every_table_is_full_refresh(self) -> None:
        # The public Business Units API exposes no server-side timestamp filter, so advertising a
        # table as incremental would silently full-scan every sync while claiming to be cheap.
        for schema in TrustPilotSource().get_schemas(_config(), team_id=1):
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_canonical_descriptions_cover_the_catalog(self) -> None:
        descriptions = TrustPilotSource().get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name in ENDPOINTS:
            assert descriptions[name].get("description")
            assert descriptions[name].get("columns")

    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("not_found", 404, False),
            ("server_error", 500, False),
            ("unreachable", None, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status: int | None, expected_valid: bool) -> None:
        with patch(f"{SOURCE_MODULE}.check_credentials", return_value=(status, None)):
            valid, error = TrustPilotSource().validate_credentials(_config(), team_id=1)

        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = TrustPilotSource().get_resumable_source_manager(MagicMock())

        assert manager._data_class is TrustpilotResumeConfig

    def test_source_for_pipeline_plumbs_credentials_and_endpoint(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "service_reviews"
        manager = MagicMock()

        with patch(f"{SOURCE_MODULE}.trustpilot_source") as mocked:
            TrustPilotSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = mocked.call_args.kwargs
        assert kwargs["api_key"] == "tp-secret"
        assert kwargs["business_unit_id"] == "46d76a9f0000640005034a5f"
        assert kwargs["endpoint"] == "service_reviews"
        assert kwargs["resumable_source_manager"] is manager

    def test_auth_and_permission_failures_are_non_retryable(self) -> None:
        errors = cast(dict[str, Any], TrustPilotSource().get_non_retryable_errors())

        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert all(message for message in errors.values())
