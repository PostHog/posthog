from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ThinkificSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source import ThinkificSource
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific import ThinkificResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source.validate_thinkific_credentials"
)


def _config(api_key: str = "key", subdomain: str = "mycompany") -> ThinkificSourceConfig:
    return ThinkificSourceConfig(api_key=api_key, subdomain=subdomain)


def _inputs(schema_name: str = "courses", **overrides: Any) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.team_id = 1
    inputs.job_id = "job"
    inputs.logger = MagicMock()
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    inputs.incremental_field = overrides.get("incremental_field", None)
    return inputs


class TestThinkificSourceConfig:
    def test_source_type(self) -> None:
        assert ThinkificSource().source_type == ExternalDataSourceType.THINKIFIC

    def test_source_config_basics(self) -> None:
        cfg = ThinkificSource().get_source_config
        assert cfg.label == "Thinkific"
        assert cfg.category == DataWarehouseSourceCategory.E_COMMERCE
        assert cfg.releaseStatus == ReleaseStatus.ALPHA
        assert cfg.unreleasedSource is True

    def test_source_config_fields(self) -> None:
        cfg = ThinkificSource().get_source_config
        fields = {f.name: f for f in cfg.fields}
        assert set(fields) == {"api_key", "subdomain"}
        api_key, subdomain = fields["api_key"], fields["subdomain"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(subdomain, SourceFieldInputConfig)
        # The secret must be a password field; the subdomain is a plain text identifier.
        assert api_key.type == "password"
        assert api_key.secret is True
        assert subdomain.type == "text"
        assert subdomain.secret is False

    def test_non_retryable_errors_cover_auth(self) -> None:
        keys = ThinkificSource().get_non_retryable_errors()
        assert any("401" in k for k in keys)
        assert any("403" in k for k in keys)


class TestThinkificGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = ThinkificSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_enrollments_is_incremental(self) -> None:
        schemas = {s.name: s for s in ThinkificSource().get_schemas(_config(), team_id=1)}
        assert schemas["enrollments"].supports_incremental is True
        assert schemas["enrollments"].incremental_fields[0]["field"] == "updated_at"
        for name in ("courses", "users", "orders", "products"):
            assert schemas[name].supports_incremental is False

    def test_names_filter(self) -> None:
        schemas = ThinkificSource().get_schemas(_config(), team_id=1, names=["courses", "users"])
        assert {s.name for s in schemas} == {"courses", "users"}


class TestThinkificValidateCredentials:
    def test_rejects_invalid_subdomain_without_calling_api(self) -> None:
        with patch(PATCH_VALIDATE) as mock_validate:
            ok, err = ThinkificSource().validate_credentials(_config(subdomain="bad domain"), team_id=1)
        assert ok is False
        assert err is not None
        mock_validate.assert_not_called()

    def test_valid_credentials(self) -> None:
        with patch(PATCH_VALIDATE, return_value=(True, 200)):
            ok, err = ThinkificSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert err is None

    @parameterized.expand(
        [
            # (status, schema_name, expected_ok) - 403 at source-create (schema None) is accepted, but a
            # per-schema 403 is surfaced as a failure.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "courses", False),
            ("unauthorized_at_create", 401, None, False),
        ]
    )
    def test_status_handling(self, _name: str, status: int, schema_name: Optional[str], expected_ok: bool) -> None:
        with patch(PATCH_VALIDATE, return_value=(False, status)):
            ok, _err = ThinkificSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok


class TestThinkificPipelinePlumbing:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = ThinkificSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ThinkificResumeConfig

    def test_source_for_pipeline_passes_incremental_value_only_when_enabled(self) -> None:
        source = ThinkificSource()
        manager = MagicMock(spec=ResumableSourceManager)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source.thinkific_source"
        ) as mock_source:
            source.source_for_pipeline(
                _config(),
                manager,
                _inputs("enrollments", should_use_incremental_field=True, db_incremental_field_last_value="2026-03-04"),
            )
        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "enrollments"
        assert kwargs["subdomain"] == "mycompany"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-03-04"

    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        source = ThinkificSource()
        manager = MagicMock(spec=ResumableSourceManager)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source.thinkific_source"
        ) as mock_source:
            source.source_for_pipeline(
                _config(),
                manager,
                _inputs("courses", should_use_incremental_field=False, db_incremental_field_last_value="2026-03-04"),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestThinkificCanonicalDescriptions:
    def test_keys_are_valid_endpoint_names(self) -> None:
        descriptions = ThinkificSource().get_canonical_descriptions()
        assert descriptions
        assert set(descriptions).issubset(set(ENDPOINTS))
