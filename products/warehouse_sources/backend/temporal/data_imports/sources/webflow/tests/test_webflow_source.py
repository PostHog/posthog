from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WebflowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import STATIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source import WebflowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import WebflowResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source"


def _config() -> WebflowSourceConfig:
    return WebflowSource().parse_config({"api_token": "token", "site_id": "site-1"})


def _inputs(schema_name: str = "pages") -> SourceInputs:
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


class TestWebflowSource:
    def test_source_type(self) -> None:
        assert WebflowSource().source_type == ExternalDataSourceType.WEBFLOW

    def test_source_config_fields_and_release_status(self) -> None:
        config = WebflowSource().get_source_config
        assert config.name == "Webflow"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is not True

        assert all(isinstance(field, SourceFieldInputConfig) for field in config.fields)
        fields = {field.name: field for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert set(fields) == {"api_token", "site_id"}
        assert fields["api_token"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_token"].secret is True
        assert fields["site_id"].type == SourceFieldInputConfigType.TEXT
        assert fields["site_id"].secret is False

    def test_get_non_retryable_errors(self) -> None:
        errors = WebflowSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "409 Client Error: Conflict" in errors

    def test_409_conflict_message_is_recognised_as_non_retryable(self) -> None:
        # Webflow returns 409 on /products when the site has no ecommerce; the raised
        # HTTPError message embeds a volatile site id and URL, so we must match on a
        # stable substring that excludes them.
        errors = WebflowSource().get_non_retryable_errors()
        raised_message = (
            "409 Client Error: Conflict for url: "
            "https://api.webflow.com/v2/sites/691afa9e7404e1259a4d0802/products?limit=100&offset=0"
        )
        matches = [pattern for pattern in errors if pattern in raised_message]
        assert matches == ["409 Client Error: Conflict"]

    def test_get_schemas_includes_static_and_dynamic_collections(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_collections",
            return_value=[{"id": "c1", "slug": "blog", "displayName": "Blog"}, {"id": "c2", "slug": "authors"}],
        ):
            schemas = WebflowSource().get_schemas(_config(), team_id=1)

        names = {s.name for s in schemas}
        assert set(STATIC_ENDPOINTS).issubset(names)
        assert "collection_blog" in names
        assert "collection_authors" in names
        # No verified server-side range filter -> everything is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_falls_back_to_static_when_discovery_fails(self) -> None:
        with patch(f"{SOURCE_MODULE}.list_collections", side_effect=Exception("no scope")):
            schemas = WebflowSource().get_schemas(_config(), team_id=1)

        assert {s.name for s in schemas} == set(STATIC_ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_collections", return_value=[{"id": "c1", "slug": "blog", "displayName": "Blog"}]
        ):
            schemas = WebflowSource().get_schemas(_config(), team_id=1, names=["sites", "collection_blog"])

        assert {s.name for s in schemas} == {"sites", "collection_blog"}

    def test_validate_credentials_plumbs_through(self) -> None:
        with patch(f"{SOURCE_MODULE}.validate_webflow_credentials", return_value=(True, None)) as mock_validate:
            ok, error = WebflowSource().validate_credentials(_config(), team_id=1, schema_name="products")

        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("token", "site-1", "products")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = WebflowSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WebflowResumeConfig

    def test_source_for_pipeline_plumbs_through(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(schema_name="collection_blog")
        with patch(f"{SOURCE_MODULE}.webflow_source") as mock_source:
            WebflowSource().source_for_pipeline(_config(), manager, inputs)

        mock_source.assert_called_once_with(
            api_token="token",
            site_id="site-1",
            schema_name="collection_blog",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
