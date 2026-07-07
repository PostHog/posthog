from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer import BeamerResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.source import BeamerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BeamerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBeamerSourceConfig:
    def setup_method(self) -> None:
        self.source = BeamerSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BEAMER

    def test_config_has_api_key_password_field(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"api_key"}
        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_config_is_released_alpha(self) -> None:
        config = self.source.get_source_config
        # A finished source is visible (no unreleasedSource) and labelled alpha.
        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/beamer"

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in BeamerSource().get_schemas(MagicMock(), team_id=1)}

    def test_all_expected_tables_present(self) -> None:
        assert set(self.schemas) == {
            "posts",
            "feature_requests",
            "nps",
            "users",
            "post_comments",
            "post_reactions",
            "feature_request_comments",
            "feature_request_votes",
        }

    @parameterized.expand(["posts", "feature_requests", "nps"])
    def test_top_level_collections_are_incremental(self, name: str) -> None:
        schema = self.schemas[name]
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date"]

    @parameterized.expand(
        ["users", "post_comments", "post_reactions", "feature_request_comments", "feature_request_votes"]
    )
    def test_full_refresh_only_tables(self, name: str) -> None:
        assert self.schemas[name].supports_incremental is False

    def test_scale_only_and_high_volume_tables_off_by_default(self) -> None:
        assert self.schemas["users"].should_sync_default is False
        assert self.schemas["post_reactions"].should_sync_default is False
        assert self.schemas["posts"].should_sync_default is True

    def test_names_filter(self) -> None:
        filtered = BeamerSource().get_schemas(MagicMock(), team_id=1, names=["posts"])
        assert [s.name for s in filtered] == ["posts"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Invalid Beamer API key")),
            ("inconclusive", (False, "Could not reach Beamer to validate the API key. Please try again.")),
        ]
    )
    def test_validate_credentials_passes_probe_result_through(self, _name: str, probe_result: tuple) -> None:
        config = BeamerSourceConfig(api_key="key")
        with patch.object(source_module, "validate_beamer_credentials", return_value=probe_result):
            assert BeamerSource().validate_credentials(config, team_id=1) == probe_result


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getbeamer.com/v0/posts?maxResults=1"),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.getbeamer.com/v0/users?maxResults=100&page=1",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BeamerSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.getbeamer.com/v0/posts"),
            ("read_timeout", "HTTPSConnectionPool(host='api.getbeamer.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = BeamerSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumablePlumbing:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = BeamerSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BeamerResumeConfig

    def test_source_for_pipeline_passes_incremental_inputs(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "posts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "date"
        config = BeamerSourceConfig(api_key="key")
        manager = MagicMock()

        with patch.object(source_module, "beamer_source") as mock_source:
            BeamerSource().source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None
        config = BeamerSourceConfig(api_key="key")

        with patch.object(source_module, "beamer_source") as mock_source:
            BeamerSource().source_for_pipeline(config, MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
