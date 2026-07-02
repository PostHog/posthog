import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GuardianSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian import GuardianResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source import GuardianSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGuardianSource:
    def setup_method(self):
        self.source = GuardianSource()
        self.config = GuardianSourceConfig(api_key="test-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GUARDIAN

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "Guardian"
        assert config.label == "The Guardian"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/guardian"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_content_supports_incremental(self):
        # /search is the sole endpoint with a server-side from-date cursor; the reference
        # catalogs (tags/sections/editions) have no timestamp filter, so they're full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert schemas["content"].supports_incremental is True
        assert schemas["content"].incremental_fields[0]["field"] == "webPublicationDate"
        for name in ("tags", "sections", "editions"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, team_id=1, names=["content", "tags"])
        assert {s.name for s in schemas} == {"content", "tags"}

    def test_lists_tables_without_credentials(self):
        # get_schemas does no I/O, so the public docs table catalog can render.
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"] for t in self.source.get_documented_tables()}
        assert documented == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://content.guardianapis.com/search",
            "403 Client Error: Forbidden for url: https://content.guardianapis.com/tags",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://content.guardianapis.com/search",
            "500 Server Error: Internal Server Error for url: https://content.guardianapis.com/search",
            "HTTPSConnectionPool(host='content.guardianapis.com', port=443): Read timed out.",
        ],
    )
    def test_transient_errors_stay_retryable(self, other_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_validate_credentials_success(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.validate_guardian_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_failure(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.validate_guardian_credentials",
            return_value=False,
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid Guardian API key"

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is GuardianResumeConfig

    def test_source_for_pipeline_plumbs_incremental_value(self):
        inputs = MagicMock()
        inputs.schema_name = "content"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.guardian_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["endpoint"] == "content"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_omits_incremental_value_when_disabled(self):
        inputs = MagicMock()
        inputs.schema_name = "tags"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source.guardian_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
