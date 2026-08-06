import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.discourse import DiscourseResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source import DiscourseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.discourse import (
    DiscourseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDiscourseSource:
    def setup_method(self) -> None:
        self.source = DiscourseSource()
        self.team_id = 123
        self.config = DiscourseSourceConfig(
            base_url="https://forum.example.com", api_key="secret-key", api_username="system"
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DISCOURSE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Discourse"
        assert config.label == "Discourse"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/discourse"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["base_url", "api_key", "api_username"]

    def test_config_has_no_unreleased_flag(self) -> None:
        # A finished source must not carry `unreleasedSource` — it hides the connector entirely.
        assert self.source.get_source_config.unreleasedSource is None

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_api_username_field_is_plain_text(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_username")
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.secret is False
        assert field.required is True

    def test_connection_host_fields_covers_base_url_and_api_username(self) -> None:
        # The stored API key is sent to whatever `base_url` points at, and `api_username` selects
        # the identity an All Users key acts as, so retargeting either must force key re-entry.
        assert self.source.connection_host_fields == ["base_url", "api_username"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_posts_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["posts"].supports_incremental is True
        assert [f["field"] for f in schemas["posts"].incremental_fields] == ["id"]
        for name, schema in schemas.items():
            if name != "posts":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["categories"])
        assert len(schemas) == 1
        assert schemas[0].name == "categories"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    @parameterized.expand(
        [
            ("403 Client Error: Forbidden for url: https://forum.example.com/session/current.json",),
            ("invalid_access",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://forum.example.com/latest.json",),
            ("429 Client Error: Too Many Requests for url: https://forum.example.com/posts.json",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source.validate_discourse_credentials"
    )
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Discourse API key or username")
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="posts")
        assert result == (False, "Invalid Discourse API key or username")
        mock_validate.assert_called_once_with(
            "https://forum.example.com", "secret-key", "system", "posts", self.team_id
        )

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DiscourseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source.discourse_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["base_url"] == "https://forum.example.com"
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["api_username"] == "system"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 42

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Discourse schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
