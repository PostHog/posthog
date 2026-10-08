from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source import DagsterCloudSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source"


class TestDagsterCloudSourceConfig:
    def test_connection_host_fields_force_token_reentry(self) -> None:
        # Both feed the *.dagster.cloud URL the token is sent to, so editing either must re-require it.
        assert set(DagsterCloudSource().connection_host_fields) == {"organization", "deployment"}


class TestDagsterCloudSchemas:
    def test_names_filter(self) -> None:
        schemas = DagsterCloudSource().get_schemas(MagicMock(), team_id=1, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]


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
