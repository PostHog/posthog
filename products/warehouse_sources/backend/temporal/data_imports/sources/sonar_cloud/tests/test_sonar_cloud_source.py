from unittest.mock import patch

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonarcloud import (
    SonarCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.source import SonarCloudSource


def _config() -> SonarCloudSourceConfig:
    return SonarCloudSourceConfig(token="tok", organization="org", region="eu")


class TestSonarCloudSourceConfig:
    def test_region_and_organization_are_connection_host_fields(self) -> None:
        # `region` retargets where the stored token is sent and `organization` retargets which tenant
        # it acts on; the update serializer must force re-entering the token when either changes.
        assert SonarCloudSource().connection_host_fields == ["region", "organization"]


class TestGetSchemas:
    def test_filters_by_name(self) -> None:
        schemas = SonarCloudSource().get_schemas(_config(), team_id=1, names=["issues"])
        assert [s.name for s in schemas] == ["issues"]


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
