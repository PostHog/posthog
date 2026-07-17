from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GNewsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.gnews import GNewsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.source import GNewsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gnews.source"


def _config(**overrides: Any) -> GNewsSourceConfig:
    defaults: dict[str, Any] = {"api_key": "k", "query": "posthog", "category": "general"}
    defaults.update(overrides)
    return GNewsSourceConfig(**defaults)


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "articles",
        "schema_id": "sid",
        "source_id": "srcid",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "jid",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestGNewsSource:
    def setup_method(self) -> None:
        self.source = GNewsSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GNEWS

    def test_get_schemas_are_incremental_and_append_on_published_at(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"articles", "top_headlines"}
        for schema in schemas.values():
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert [f["field"] for f in schema.incremental_fields] == ["publishedAt"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["top_headlines"])
        assert [s.name for s in schemas] == ["top_headlines"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert {t["name"] for t in self.source.get_documented_tables()} == {"articles", "top_headlines"}

    @parameterized.expand([("401 Client Error",), ("403 Client Error",)])
    def test_non_retryable_errors(self, expected_substring: str) -> None:
        assert any(expected_substring in key for key in self.source.get_non_retryable_errors())

    @parameterized.expand([(True, None), (False, "Invalid GNews API key")])
    def test_validate_credentials_delegates(self, valid: bool, message: str | None) -> None:
        with patch(f"{_MODULE}.validate_gnews_credentials", return_value=(valid, message)) as mock_validate:
            result = self.source.validate_credentials(_config(api_key="secret"), team_id=1)
        mock_validate.assert_called_once_with("secret")
        assert result == (valid, message)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GNewsResumeConfig

    def test_source_for_pipeline_plumbs_config_and_schema(self) -> None:
        config = _config(query="analytics", category="technology", language="en", country="us")
        with patch(f"{_MODULE}.gnews_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), _inputs(schema_name="top_headlines"))
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["endpoint"] == "top_headlines"
        assert kwargs["query"] == "analytics"
        assert kwargs["category"] == "technology"
        assert kwargs["language"] == "en"
        assert kwargs["country"] == "us"

    def test_source_for_pipeline_suppresses_last_value_when_not_incremental(self) -> None:
        # A stale last-value must not leak into a full-refresh sync.
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01T00:00:00Z")
        with patch(f"{_MODULE}.gnews_source") as mock_source:
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
