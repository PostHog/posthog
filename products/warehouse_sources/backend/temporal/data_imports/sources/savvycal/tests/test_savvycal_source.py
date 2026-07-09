import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SavvyCalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal import SavvyCalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source import SavvyCalSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSavvyCalSource:
    def setup_method(self) -> None:
        self.source = SavvyCalSource()
        self.team_id = 123
        self.config = SavvyCalSourceConfig(api_key="pt_secret_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SAVVYCAL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SavvyCal"
        assert config.label == "SavvyCal"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/savvycal"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret token; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved token against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_events_support_incremental(self) -> None:
        # Only /events exposes a server-side cursor (`from` on start date); advertising incremental
        # on any other stream would silently sync nothing new.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["events"].supports_incremental is True
        assert [f["field"] for f in schemas["events"].incremental_fields] == ["start_at"]
        for name in set(ENDPOINTS) - {"events"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["links"])
        assert len(schemas) == 1
        assert schemas[0].name == "links"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.savvycal.com/v1/events",),
            ("403 Client Error: Forbidden for url: https://api.savvycal.com/v1/me",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.savvycal.com/v1/events",),
            ("429 Client Error: Too Many Requests for url: https://api.savvycal.com/v1/links",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the token to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid SavvyCal personal access token")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid SavvyCal personal access token")
        mock_validate.assert_called_once_with("pt_secret_key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SavvyCalResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.savvycal_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pt_secret_key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.savvycal_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark from a previous incremental config must not leak into a full refresh.
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SavvyCal schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
