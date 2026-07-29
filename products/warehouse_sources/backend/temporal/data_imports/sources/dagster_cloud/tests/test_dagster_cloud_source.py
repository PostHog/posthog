from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.dagster_cloud import (
    DagsterCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source import DagsterCloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source"


class TestDagsterCloudSourceConfig:
    def test_source_type(self) -> None:
        assert DagsterCloudSource().source_type == ExternalDataSourceType.DAGSTERCLOUD

    def test_config_is_released_alpha_not_hidden(self) -> None:
        config = DagsterCloudSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source must be visible; unreleasedSource would hide it from every user.
        assert config.unreleasedSource is None

    def test_config_fields(self) -> None:
        fields: dict[str, SourceFieldInputConfig] = {}
        for field in DagsterCloudSource().get_source_config.fields:
            assert isinstance(field, SourceFieldInputConfig)
            fields[field.name] = field
        assert set(fields) == {"organization", "deployment", "api_token"}
        assert all(f.required for f in fields.values())
        # The token is the only secret; it must be a password input so it's stored encrypted.
        assert fields["api_token"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_token"].secret is True

    def test_connection_host_fields_force_token_reentry(self) -> None:
        # Both feed the *.dagster.cloud URL the token is sent to, so editing either must re-require it.
        assert set(DagsterCloudSource().connection_host_fields) == {"organization", "deployment"}


class TestDagsterCloudSchemas:
    def test_schema_incremental_flags(self) -> None:
        schemas = {s.name: s for s in DagsterCloudSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"runs", "backfills", "assets"}
        assert schemas["runs"].supports_incremental is True
        assert {f["field"] for f in schemas["runs"].incremental_fields} == {"updateTime", "creationTime"}
        assert schemas["backfills"].supports_incremental is False
        assert schemas["assets"].supports_incremental is False
        # Runs mutate after creation, so append-only would duplicate rows — merge only, everywhere.
        assert all(s.supports_append is False for s in schemas.values())

    def test_names_filter(self) -> None:
        schemas = DagsterCloudSource().get_schemas(MagicMock(), team_id=1, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True — the static catalog must surface in public docs.
        tables = {t["name"]: t for t in DagsterCloudSource().get_documented_tables()}
        assert set(tables) == {"runs", "backfills", "assets"}
        assert tables["runs"]["description"]  # canonical description present
        assert "Incremental" in tables["runs"]["sync_methods"]
        assert "Incremental" not in tables["assets"]["sync_methods"]


class TestDagsterCloudNonRetryableErrors:
    @parameterized.expand(
        [
            ("auth_401", "401 Client Error: Unauthorized for url: https://acme.dagster.cloud/prod/graphql"),
            ("forbidden_403", "403 Client Error: Forbidden for url: https://acme.dagster.cloud/prod/graphql"),
        ]
    )
    def test_matches_permanent_failures(self, _name: str, observed: str) -> None:
        errors = DagsterCloudSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("server_500", "500 Client Error: Internal Server Error for url: https://acme.dagster.cloud/prod/graphql"),
            ("rate_limited", "Dagster Cloud: rate limited (429)"),
            ("network", "Dagster Cloud: transient network error - Read timed out"),
        ]
    )
    def test_leaves_transient_errors_retryable(self, _name: str, observed: str) -> None:
        errors = DagsterCloudSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestDagsterCloudPlumbing:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = DagsterCloudSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is DagsterCloudResumeConfig

    @patch(f"{MODULE}.validate_dagster_cloud_credentials")
    def test_validate_credentials_passes_config_fields(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = MagicMock(organization="acme", deployment="prod", api_token="tok")

        DagsterCloudSource().validate_credentials(config, team_id=1)

        mock_validate.assert_called_once_with("acme", "prod", "tok")

    @patch(f"{MODULE}.dagster_cloud_source")
    def test_source_for_pipeline_gates_incremental_value(self, mock_source: MagicMock) -> None:
        config = MagicMock(organization="acme", deployment="prod", api_token="tok")
        inputs = MagicMock(
            schema_name="runs",
            should_use_incremental_field=False,
            db_incremental_field_last_value="should-be-dropped",
            incremental_field="updateTime",
        )

        DagsterCloudSource().source_for_pipeline(config, MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["endpoint_name"] == "runs"
        assert kwargs["organization"] == "acme"
        # A non-incremental run must not leak a stale watermark into the request.
        assert kwargs["db_incremental_field_last_value"] is None
