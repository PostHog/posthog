import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh import CodefreshResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source import CodefreshSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodefreshSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCodefreshSource:
    def setup_method(self) -> None:
        self.source = CodefreshSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CODEFRESH

    def test_source_config_has_api_key_password_field(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Codefresh"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/codefresh"
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key"]
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == "password"
        assert api_key_field.required is True

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://g.codefresh.io/api/projects?limit=100&offset=0",),
            ("403 Client Error: Forbidden for url: https://g.codefresh.io/api/workflow?limit=100&page=1",),
        ]
    )
    def test_credential_errors_are_non_retryable(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='g.codefresh.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://g.codefresh.io/api/projects"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://g.codefresh.io/api/workflow"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(CodefreshSourceConfig(api_key="t"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            # Codefresh has no server-side updated-since filter, so every table is full refresh only.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(CodefreshSourceConfig(api_key="t"), self.team_id, names=["builds"])
        assert [s.name for s in schemas] == ["builds"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the public docs may render the table catalog.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("valid", True, None, True),
            ("invalid", False, "Your Codefresh API key is invalid or has been revoked.", False),
        ]
    )
    def test_validate_credentials_plumbs_through(
        self, _name: str, inner_valid: bool, inner_error: str | None, expected_valid: bool
    ) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source.validate_codefresh_credentials",
            return_value=(inner_valid, inner_error),
        ) as mocked:
            valid, error = self.source.validate_credentials(CodefreshSourceConfig(api_key="t"), self.team_id)
        mocked.assert_called_once_with("t", schema_name=None)
        assert valid is expected_valid
        if not expected_valid:
            assert error == inner_error

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CodefreshResumeConfig

    def test_source_for_pipeline_passes_schema_name_as_endpoint(self) -> None:
        config = CodefreshSourceConfig(api_key="secret")
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source.codefresh_source"
        ) as mocked_source:
            self.source.source_for_pipeline(config, manager, inputs)

        mocked_source.assert_called_once()
        kwargs = mocked_source.call_args.kwargs
        assert kwargs["api_key"] == "secret"
        assert kwargs["endpoint"] == "builds"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        # Every documented endpoint must be a real endpoint, and the high-value tables are covered.
        assert set(canonical).issubset(set(ENDPOINTS))
        for name in ("projects", "pipelines", "builds", "images"):
            assert name in canonical


if __name__ == "__main__":
    pytest.main([__file__])
