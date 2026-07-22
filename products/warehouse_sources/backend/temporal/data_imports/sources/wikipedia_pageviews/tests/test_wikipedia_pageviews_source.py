from types import SimpleNamespace
from typing import cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wikipediapageviews import (
    WikipediaPageviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    ENDPOINTS,
    MAX_ARTICLES,
    PAGEVIEWS_ENDPOINT,
    WIKIPEDIA_PAGEVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.source import (
    WikipediaPageviewsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.wikipedia_pageviews import (
    NO_ARTICLES_ERROR,
    WikipediaPageviewsResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.source"


class TestWikipediaPageviewsSource:
    def setup_method(self):
        self.source = WikipediaPageviewsSource()
        self.team_id = 123
        self.config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WIKIPEDIAPAGEVIEWS

    def test_get_source_config_is_released(self):
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.name.value == "WikipediaPageviews"
        assert config.iconPath == "/static/services/wikipedia_pageviews.png"

        fields_by_name = {field.name: field for field in config.fields}
        assert set(fields_by_name) == {"project", "access", "agent", "article_names", "start_date"}

        project = fields_by_name["project"]
        assert isinstance(project, SourceFieldInputConfig)
        assert project.required is True

        access = fields_by_name["access"]
        assert isinstance(access, SourceFieldSelectConfig)
        assert access.defaultValue == "all-access"

        agent = fields_by_name["agent"]
        assert isinstance(agent, SourceFieldSelectConfig)
        assert agent.defaultValue == "user"

        assert cast(SourceFieldInputConfig, fields_by_name["article_names"]).required is False
        assert cast(SourceFieldInputConfig, fields_by_name["start_date"]).required is False

    def test_get_schemas_returns_every_endpoint_with_incremental_date(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert {field["field"] for field in schema.incremental_fields} == {"date"}

    @parameterized.expand(
        [
            ("no_articles", None, False),
            ("with_articles", "Albert Einstein", True),
        ]
    )
    def test_article_pageviews_default_sync_requires_articles(self, _name, article_names, expected_default):
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", article_names=article_names)
        schema = next(s for s in self.source.get_schemas(config, self.team_id) if s.name == ARTICLE_PAGEVIEWS_ENDPOINT)
        assert schema.should_sync_default is expected_default

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[PAGEVIEWS_ENDPOINT])
        assert [schema.name for schema in schemas] == [PAGEVIEWS_ENDPOINT]

    def test_non_retryable_errors_cover_missing_articles(self):
        assert NO_ARTICLES_ERROR in self.source.get_non_retryable_errors()

    def test_validate_credentials_rejects_bad_start_date(self):
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", start_date="not-a-date")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "YYYY-MM-DD" in message

    def test_validate_credentials_rejects_too_many_articles(self):
        names = ",".join(f"Article_{i}" for i in range(MAX_ARTICLES + 1))
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", article_names=names)
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and str(MAX_ARTICLES) in message

    def test_validate_credentials_rejects_article_schema_without_articles(self):
        is_valid, message = self.source.validate_credentials(
            self.config, self.team_id, schema_name=ARTICLE_PAGEVIEWS_ENDPOINT
        )
        assert is_valid is False
        assert message is not None and "article" in message.lower()

    @mock.patch(f"{MODULE}.validate_project")
    def test_validate_credentials_plumbs_to_validate_project(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert message is None
        mock_validate.assert_called_once_with("en.wikipedia.org", "all-access", "user")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WikipediaPageviewsResumeConfig

    @mock.patch(f"{MODULE}.wikipedia_pageviews_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_source):
        mock_source.return_value = SimpleNamespace(name=PAGEVIEWS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(
            schema_name=PAGEVIEWS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-1",
            logger=logger,
            should_use_incremental_field=True,
            incremental_field="date",
            db_incremental_field_last_value="2026-07-01",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_source.assert_called_once_with(
            project="en.wikipedia.org",
            access="all-access",
            agent="user",
            article_names=None,
            start_date=None,
            endpoint=PAGEVIEWS_ENDPOINT,
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01",
        )
        assert response is mock_source.return_value

    @mock.patch(f"{MODULE}.wikipedia_pageviews_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source):
        mock_source.return_value = SimpleNamespace(name=PAGEVIEWS_ENDPOINT)
        inputs = SimpleNamespace(
            schema_name=PAGEVIEWS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-07-01",
        )

        self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), cast(SourceInputs, inputs)
        )

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(WIKIPEDIA_PAGEVIEWS_ENDPOINTS)
        for table in tables:
            assert table["description"]
