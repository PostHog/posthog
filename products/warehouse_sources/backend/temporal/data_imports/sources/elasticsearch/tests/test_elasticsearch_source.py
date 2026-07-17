import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.source import (
    ElasticsearchSource,
    _auth_from_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ElasticsearchAuthMethodConfig,
    ElasticsearchSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.elasticsearch.source"


def _config(selection: str = "basic") -> ElasticsearchSourceConfig:
    return ElasticsearchSourceConfig(
        host="https://es.example.com:9243",
        auth_method=ElasticsearchAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            username="elastic",
            password="pw",
            api_key="key123",
        ),
    )


class TestAuthFromConfig:
    def test_basic_selection(self):
        auth = _auth_from_config(_config("basic"))
        assert auth.username == "elastic"
        assert auth.password == "pw"
        assert auth.api_key is None

    def test_api_key_selection(self):
        auth = _auth_from_config(_config("api_key"))
        assert auth.api_key == "key123"
        assert auth.username is None


class TestElasticsearchSource:
    def setup_method(self):
        self.source = ElasticsearchSource()
        self.team_id = 123
        self.config = _config()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ELASTICSEARCH

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Elasticsearch"
        assert config.label == "Elasticsearch"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/elasticsearch.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "auth_method"]

    def test_auth_method_is_a_select_with_basic_and_api_key(self):
        config = self.source.get_source_config
        auth_field = next(f for f in config.fields if f.name == "auth_method")
        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert {option.value for option in auth_field.options} == {"basic", "api_key"}

    def test_secret_subfields_are_marked_secret(self):
        config = self.source.get_source_config
        auth_field = next(f for f in config.fields if f.name == "auth_method")
        assert isinstance(auth_field, SourceFieldSelectConfig)
        subfields = [f for option in auth_field.options for f in (option.fields or [])]
        secret_names = {f.name for f in subfields if isinstance(f, SourceFieldInputConfig) and f.secret}
        assert secret_names == {"password", "api_key"}

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://es.example.com:9243/orders/_search",
            "403 Client Error: Forbidden for url: https://es.example.com:9243/_cat/indices",
            "404 Client Error: Not Found for url: https://es.example.com:9243/gone/_search",
            "ValueError: Elasticsearch returned a non-JSON response. Check that the cluster URL points at the Elasticsearch HTTP API, not a browser or Kibana URL.",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://es.example.com:9243/orders/_search"
            for key in non_retryable_errors
        )

    @mock.patch(f"{_SOURCE_MODULE}.list_indices")
    def test_get_schemas_lists_indices_full_refresh_only(self, mock_list):
        mock_list.return_value = ["accounts", "orders"]

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["accounts", "orders"]
        assert all(not s.supports_incremental for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    @mock.patch(f"{_SOURCE_MODULE}.list_indices")
    def test_get_schemas_filtered_by_names(self, mock_list):
        mock_list.return_value = ["accounts", "orders"]

        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])

        assert [s.name for s in schemas] == ["orders"]

    @mock.patch(f"{_SOURCE_MODULE}.validate_elasticsearch_credentials")
    @mock.patch.object(ElasticsearchSource, "is_database_host_valid")
    def test_validate_credentials_checks_host_then_connection(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = True

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_host_valid.assert_called_once_with("es.example.com", self.team_id)

    @mock.patch.object(ElasticsearchSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error == "Host is not allowed"

    def test_validate_credentials_rejects_malformed_host(self):
        config = _config()
        config.host = "ftp://nope"

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Invalid Elasticsearch cluster URL"

    @mock.patch(f"{_SOURCE_MODULE}.elasticsearch_source")
    @mock.patch.object(ElasticsearchSource, "is_database_host_valid")
    def test_source_for_pipeline_rechecks_host(self, mock_host_valid, mock_es_source):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, inputs)

        mock_es_source.assert_not_called()

    @mock.patch(f"{_SOURCE_MODULE}.elasticsearch_source")
    @mock.patch.object(ElasticsearchSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_es_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.schema_name = "orders"

        self.source.source_for_pipeline(self.config, inputs)

        mock_es_source.assert_called_once()
        kwargs = mock_es_source.call_args.kwargs
        assert kwargs["host"] == "https://es.example.com:9243"
        assert kwargs["index"] == "orders"
        assert kwargs["auth"].username == "elastic"
