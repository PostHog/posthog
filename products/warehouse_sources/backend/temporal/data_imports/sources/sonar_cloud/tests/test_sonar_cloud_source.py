from unittest.mock import patch

import structlog
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonarCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.source import SonarCloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> SonarCloudSourceConfig:
    return SonarCloudSourceConfig(token="tok", organization="org", region="eu")


class TestSonarCloudSourceConfig:
    def test_source_type(self) -> None:
        assert SonarCloudSource().source_type == ExternalDataSourceType.SONARCLOUD

    def test_is_visible_not_unreleased(self) -> None:
        # A finished source must be visible: unreleasedSource hides it from every user.
        assert SonarCloudSource().get_source_config.unreleasedSource in (None, False)

    def test_config_fields(self) -> None:
        fields = {f.name: f for f in SonarCloudSource().get_source_config.fields}
        assert set(fields) == {"token", "organization", "region"}
        token_field = fields["token"]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.secret is True
        region_field = fields["region"]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "eu"

    def test_region_and_organization_are_connection_host_fields(self) -> None:
        # `region` retargets where the stored token is sent and `organization` retargets which tenant
        # it acts on; the update serializer must force re-entering the token when either changes.
        assert SonarCloudSource().connection_host_fields == ["region", "organization"]


class TestGetSchemas:
    def test_lists_every_endpoint_full_refresh(self) -> None:
        schemas = SonarCloudSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint has a verified server-side update cursor, so all are full refresh.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)

    def test_filters_by_name(self) -> None:
        schemas = SonarCloudSource().get_schemas(_config(), team_id=1, names=["issues"])
        assert [s.name for s in schemas] == ["issues"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials must produce the public-docs table catalog.
        tables = SonarCloudSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "issues", False),
            ("transport_error", 0, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(source_module, "validate_sonar_cloud_credentials", return_value=status):
            ok, _ = SonarCloudSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok


class TestResumableWiring:
    def test_resumable_manager_bound_to_config(self) -> None:
        manager = SonarCloudSource().get_resumable_source_manager(_fake_inputs())
        assert manager._data_class is SonarCloudResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _fake_inputs(schema_name="issues")
        source = SonarCloudSource()
        with patch.object(source_module, "sonar_cloud_source") as sonar_source:
            source.source_for_pipeline(_config(), source.get_resumable_source_manager(inputs), inputs)
        _, kwargs = sonar_source.call_args
        assert kwargs["token"] == "tok"
        assert kwargs["organization"] == "org"
        assert kwargs["region"] == "eu"
        assert kwargs["endpoint"] == "issues"


class TestNonRetryableErrors:
    def test_covers_both_region_hosts(self) -> None:
        errors = SonarCloudSource().get_non_retryable_errors()
        assert "401 Client Error: Unauthorized for url: https://sonarcloud.io/api" in errors
        assert "401 Client Error: Unauthorized for url: https://sonarqube.us/api" in errors
        assert "403 Client Error: Forbidden for url: https://sonarcloud.io/api" in errors


def _fake_inputs(schema_name: str = "projects") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="s",
        source_id="src",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )
