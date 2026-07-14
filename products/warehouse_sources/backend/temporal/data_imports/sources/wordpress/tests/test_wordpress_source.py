import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source import WordpressSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import WordpressResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWordpressSource:
    def setup_method(self):
        self.source = WordpressSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.site_url = "https://example.com"
        self.config.username = "admin"
        self.config.application_password = "app pass word"

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WORDPRESS

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["site_url"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Wordpress"
        assert config.label == "WordPress"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

        field_names = [f.name for f in config.fields]
        assert field_names == ["site_url", "username", "application_password"]

        site_field, user_field, pass_field = config.fields
        assert isinstance(site_field, SourceFieldInputConfig)
        assert site_field.type == SourceFieldInputConfigType.TEXT
        assert site_field.required is True
        assert site_field.secret is False

        assert isinstance(user_field, SourceFieldInputConfig)
        assert user_field.required is False
        assert user_field.secret is False

        assert isinstance(pass_field, SourceFieldInputConfig)
        assert pass_field.type == SourceFieldInputConfigType.PASSWORD
        assert pass_field.required is False
        assert pass_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "404 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("posts", True),
            ("pages", True),
            ("comments", True),
            ("media", True),
            ("categories", False),
            ("tags", False),
            ("users", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    @pytest.mark.parametrize(
        "endpoint, fields",
        [
            ("posts", {"modified", "date"}),
            ("comments", {"date"}),
            ("categories", set()),
        ],
    )
    def test_advertised_incremental_fields(self, endpoint, fields):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert {f["field"] for f in schemas[endpoint].incremental_fields} == fields

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            (
                (False, "Invalid WordPress username or application password"),
                (False, "Invalid WordPress username or application password"),
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source.validate_wordpress_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="posts")

        assert result == expected
        mock_validate.assert_called_once_with(
            self.config.site_url, self.config.username, self.config.application_password, self.team_id
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WordpressResumeConfig

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source.wordpress_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_wordpress_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00"
        inputs.incremental_field = "modified"

        manager = mock.MagicMock()
        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_wordpress_source.assert_called_once()
        kwargs = mock_wordpress_source.call_args.kwargs
        assert kwargs["site_url"] == "https://example.com"
        assert kwargs["username"] == "admin"
        assert kwargs["application_password"] == "app pass word"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00"
        assert kwargs["incremental_field"] == "modified"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source.wordpress_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_wordpress_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "categories"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_wordpress_source.call_args.kwargs["db_incremental_field_last_value"] is None
