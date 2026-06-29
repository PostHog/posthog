from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import (
    AUTH_ERROR_MESSAGE,
    BigMailerResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.source import BigMailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BigMailerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key") -> BigMailerSourceConfig:
    return cast(BigMailerSourceConfig, BigMailerSource()._config_class(api_key=api_key))


def _inputs(schema_name: str) -> SourceInputs:
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


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert BigMailerSource().source_type == ExternalDataSourceType.BIGMAILER

    def test_config_identity_and_release(self) -> None:
        config = BigMailerSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.BIG_MAILER
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        # shipped as a hidden alpha: unreleasedSource keeps it out of the catalog until it's validated
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/bigmailer"

    def test_single_password_api_key_field(self) -> None:
        fields = cast(list[SourceFieldInputConfig], BigMailerSource().get_source_config.fields)
        assert [f.name for f in fields] == ["api_key"]
        assert fields[0].type == SourceFieldInputConfigType.PASSWORD
        assert fields[0].required is True


class TestGetSchemas:
    def test_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = BigMailerSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # BigMailer has no server-side time filter, so no table may advertise incremental or append
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_users_is_not_synced_by_default(self) -> None:
        # account-level admin data shouldn't be pulled unless the user opts in; the marketing tables should
        by_name = {s.name: s for s in BigMailerSource().get_schemas(_config(), team_id=1)}
        assert by_name["users"].should_sync_default is False
        assert by_name["contacts"].should_sync_default is True

    def test_names_filter(self) -> None:
        schemas = BigMailerSource().get_schemas(_config(), team_id=1, names=["contacts", "lists"])
        assert {s.name for s in schemas} == {"contacts", "lists"}


class TestDocumentedTables:
    def test_renders_table_catalog_without_credentials(self) -> None:
        # lists_tables_without_credentials must stay on so posthog.com renders the Supported tables section
        assert BigMailerSource().lists_tables_without_credentials is True
        tables = BigMailerSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        brands = next(t for t in tables if t["name"] == "brands")
        assert brands["sync_methods"] == ["Full refresh"]
        assert brands["description"]  # canonical description is wired up


class TestCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials_plumbing(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_bigmailer_credentials", return_value=probe_result):
            ok, error = BigMailerSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_non_retryable_errors_cover_auth_failure(self) -> None:
        errors = BigMailerSource().get_non_retryable_errors()
        assert AUTH_ERROR_MESSAGE in errors
        assert errors[AUTH_ERROR_MESSAGE]  # has a user-facing message


class TestPipelineHandoff:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = BigMailerSource().get_resumable_source_manager(_inputs("contacts"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BigMailerResumeConfig

    @parameterized.expand([("contacts", ["brand_id", "id"]), ("brands", ["id"])])
    def test_source_for_pipeline_builds_response(self, endpoint: str, expected_keys: list[str]) -> None:
        src = BigMailerSource()
        inputs = _inputs(endpoint)
        response = src.source_for_pipeline(_config(), src.get_resumable_source_manager(inputs), inputs)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
