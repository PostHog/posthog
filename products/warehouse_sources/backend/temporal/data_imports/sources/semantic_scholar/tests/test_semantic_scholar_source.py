from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.source import (
    SemanticScholarSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.source"


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


class TestSemanticScholarSource:
    def setup_method(self) -> None:
        self.source = SemanticScholarSource()
        self.config = SemanticScholarSourceConfig(query="quantum computing")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SEMANTICSCHOLAR

    def test_source_ships_visible_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.label == "Semantic Scholar"
        assert config.iconPath == "/static/services/semantic_scholar.png"

    def test_fields(self) -> None:
        fields = [f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)]

        assert [f.name for f in fields] == ["query", "author_query", "api_key"]

        query, author_query, api_key = fields
        assert query.required is True
        assert query.secret is False
        assert author_query.required is False
        assert author_query.secret is False
        assert api_key.required is False
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD

    def test_get_schemas_lists_every_endpoint_without_credentials(self) -> None:
        schemas = self.source.get_schemas(SemanticScholarSourceConfig(query=""), team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["Papers"])

        assert {schema.name for schema in schemas} == {"Papers"}

    def test_only_papers_advertises_incremental_sync(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert schemas["Papers"].supports_incremental is True
        assert [f["field"] for f in schemas["Papers"].incremental_fields] == ["publicationDate"]
        assert schemas["Authors"].supports_incremental is False
        assert schemas["Authors"].incremental_fields == []

    def test_incremental_fields_only_cover_known_endpoints(self) -> None:
        assert set(INCREMENTAL_FIELDS) <= set(ENDPOINTS)

    def test_canonical_descriptions_are_keyed_by_schema_name(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) <= set(ENDPOINTS)

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("Papers"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SemanticScholarResumeConfig

    @patch(f"{SOURCE_MODULE}.semantic_scholar_source")
    def test_source_for_pipeline_passes_both_queries_through(self, mock_source: MagicMock) -> None:
        config = SemanticScholarSourceConfig(query="quantum computing", author_query="Jane Smith", api_key="key")

        self.source.source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), _inputs("Papers"))

        assert mock_source.call_args.kwargs["query"] == "quantum computing"
        assert mock_source.call_args.kwargs["author_query"] == "Jane Smith"
        assert mock_source.call_args.kwargs["api_key"] == "key"
        assert mock_source.call_args.kwargs["endpoint"] == "Papers"

    @patch(f"{SOURCE_MODULE}.validate_paper_search")
    def test_validate_credentials_checks_the_paper_query_by_default(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = SemanticScholarSourceConfig(query="quantum computing", api_key="key")

        assert self.source.validate_credentials(config, team_id=1) == (True, None)

        mock_validate.assert_called_once_with("key", "quantum computing")

    def test_validate_credentials_rejects_a_blank_author_query_for_the_authors_schema(self) -> None:
        config = SemanticScholarSourceConfig(query="quantum computing", author_query=None)

        ok, error = self.source.validate_credentials(config, team_id=1, schema_name="Authors")

        assert ok is False
        assert error == "Enter an author search query to sync the Authors table."

    @patch(f"{SOURCE_MODULE}.validate_author_search")
    def test_validate_credentials_checks_the_author_query_for_the_authors_schema(
        self, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = (True, None)
        config = SemanticScholarSourceConfig(query="quantum computing", author_query="Jane Smith", api_key="key")

        assert self.source.validate_credentials(config, team_id=1, schema_name="Authors") == (True, None)

        mock_validate.assert_called_once_with("key", "Jane Smith")

    def test_auth_and_query_failures_are_non_retryable(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert any("403 Client Error: Forbidden" in pattern for pattern in errors)
        assert any("400 Client Error: Bad Request" in pattern and "paper/search/bulk" in pattern for pattern in errors)
        assert any("400 Client Error: Bad Request" in pattern and "author/search" in pattern for pattern in errors)
