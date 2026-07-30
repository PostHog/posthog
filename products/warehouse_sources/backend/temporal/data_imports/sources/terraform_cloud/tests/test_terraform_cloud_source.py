from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source import TerraformCloudSource
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud import (
    TerraformCloudResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_token: str = "test-token", organization: str = "acme") -> TerraformCloudSourceConfig:
    return TerraformCloudSourceConfig.from_dict({"api_token": api_token, "organization": organization})


def _inputs(schema_name: str, should_use_incremental_field: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestTerraformCloudSource:
    def test_source_type(self) -> None:
        assert TerraformCloudSource().source_type == ExternalDataSourceType.TERRAFORMCLOUD

    def test_source_config_shape(self) -> None:
        config = TerraformCloudSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source must be visible — unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/terraform-cloud"
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token", "organization"]
        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.secret is True

    def test_get_schemas_incremental_flags(self) -> None:
        # Only the newest-first, created_at-cursorable child endpoints may advertise
        # incremental; the org-level lists have no cursor and must stay full refresh.
        schemas = {s.name: s for s in TerraformCloudSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"organizations", "projects", "teams", "workspaces", "runs", "state_versions"}
        for name in ("runs", "state_versions"):
            assert schemas[name].supports_incremental is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["created_at"]
        for name in ("organizations", "projects", "teams", "workspaces"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = TerraformCloudSource().get_schemas(_config(), team_id=1, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]

    @parameterized.expand(
        [
            ("bad org/../path", False),
            ("has space", False),
            ("", False),
        ]
    )
    def test_validate_credentials_rejects_invalid_org_names_without_network(self, organization: str, _: bool) -> None:
        # The org name lands in a URL path; a malformed value must be rejected before any request.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials"
        ) as probe:
            ok, message = TerraformCloudSource().validate_credentials(_config(organization=organization), team_id=1)
        assert ok is False
        assert message is not None
        probe.assert_not_called()

    def test_validate_credentials_delegates_probe(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials",
            return_value=(True, None),
        ) as probe:
            assert TerraformCloudSource().validate_credentials(_config(), team_id=1) == (True, None)
        probe.assert_called_once_with("test-token", "acme")

    def test_resumable_source_manager_binds_resume_dataclass(self) -> None:
        manager = TerraformCloudSource().get_resumable_source_manager(_inputs("runs"))
        assert manager._data_class is TerraformCloudResumeConfig

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://app.terraform.io/api/v2/workspaces/ws-1/runs",),
            ("403 Client Error: Forbidden for url: https://app.terraform.io/api/v2/organizations/acme/teams",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked token must permanently fail the sync rather than retry forever; the matcher
        # keys on the stable status text + host, so real HTTPError strings match.
        errors = TerraformCloudSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())

    @parameterized.expand([(True, "2026-01-01T00:00:00Z"), (False, None)])
    def test_source_for_pipeline_plumbs_arguments(self, should_use_incremental: bool, expected_last_value: Any) -> None:
        sentinel = object()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.terraform_cloud_source",
            return_value=sentinel,
        ) as mock_source:
            inputs = _inputs("runs", should_use_incremental_field=should_use_incremental)
            result = TerraformCloudSource().source_for_pipeline(_config(organization=" acme "), manager, inputs)

        assert result is sentinel
        mock_source.assert_called_once_with(
            api_token="test-token",
            organization="acme",  # stripped so a pasted name with whitespace doesn't 404 every request
            endpoint="runs",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=expected_last_value,
        )

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials powers the public docs table catalog; it must resolve
        # from the static endpoint catalog with no network call and merge canonical descriptions.
        tables = TerraformCloudSource().get_documented_tables()
        by_name: dict[str, dict[str, Any]] = {t["name"]: t for t in tables}
        assert set(by_name) == {"organizations", "projects", "teams", "workspaces", "runs", "state_versions"}
        assert by_name["runs"]["sync_methods"] == ["Incremental", "Full refresh"]
        assert by_name["workspaces"]["sync_methods"] == ["Full refresh"]
        assert by_name["runs"]["description"]
