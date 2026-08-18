from datetime import UTC, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import DecagonResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source import DecagonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.decagon import (
    DecagonSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "conversations")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value")
    inputs.incremental_field = overrides.get("incremental_field")
    return inputs


class TestDecagonSource:
    def setup_method(self) -> None:
        self.source = DecagonSource()
        self.team_id = 123
        self.config = DecagonSourceConfig(api_key="decagon-test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DECAGON

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Decagon"
        assert config.label == "Decagon"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_get_schemas_advertises_incremental_but_not_append(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        conversations = next(s for s in schemas if s.name == "conversations")
        # The export filters server-side on updated_at (min_timestamp + timestamp_filter),
        # so incremental sync is real. Append stays off: a conversation re-enters the
        # export whenever it receives new messages, so an append sync would accumulate one
        # copy per mutation instead of merging them.
        assert conversations.supports_incremental is True
        assert conversations.supports_append is False
        assert [f["field"] for f in conversations.incremental_fields] == ["updated_at"]

        actions = next(s for s in schemas if s.name == "agent_assist_actions")
        # No documented unique id means no merge key, so append (windowed on created_at)
        # and full refresh are the only sync types that cannot lose or merge rows.
        assert actions.supports_incremental is False
        assert actions.supports_append is True
        assert [f["field"] for f in actions.incremental_fields] == ["created_at"]

        articles = next(s for s in schemas if s.name == "articles")
        # The catalog has no server-side timestamp filter, so no incremental option; the
        # table also starts unselected until article body sizes are confirmed safe.
        assert articles.supports_incremental is False
        assert articles.supports_append is False
        assert articles.should_sync_default is False

        usage = next(s for s in schemas if s.name == "article_usage")
        assert usage.supports_incremental is False
        assert usage.supports_append is False

        tags = next(s for s in schemas if s.name == "tags")
        # /tag/all has no server-side timestamp filter, so only full refresh is honest.
        assert tags.supports_incremental is False
        assert tags.supports_append is False

        admin_logs = next(s for s in schemas if s.name == "admin_logs")
        # Merge on id keeps the table correct even if the loosely typed `start` filter is
        # ignored server-side; an append sync in that case would re-add all history every
        # run, so it is not offered. Opt-in until the details columns are confirmed safe.
        assert admin_logs.supports_incremental is True
        assert admin_logs.supports_append is False
        assert admin_logs.should_sync_default is False
        assert [f["field"] for f in admin_logs.incremental_fields] == ["created_at"]

        members = next(s for s in schemas if s.name == "team_members")
        # Staff email addresses must be a deliberate opt-in, not something an account
        # acquires by connecting the source.
        assert members.should_sync_default is False
        assert members.supports_incremental is False

        watchtower = next(s for s in schemas if s.name == "watchtower_jobs")
        assert watchtower.supports_incremental is False
        assert watchtower.supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["conversations"])] == [
            "conversations"
        ]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors

    @parameterized.expand(
        [
            (
                "connection_error_wrapping_read_timeout",
                "HTTPSConnectionPool(host='api.decagon.ai', port=443): Max retries exceeded with url: "
                "/conversation/export (Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='api.decagon.ai', "
                'port=443): Read timed out. (read timeout=60)"))',
            ),
            (
                "exhausted_retryable_status",
                "Decagon API error (retryable): status=503, url=https://api.decagon.ai/tag/all",
            ),
        ]
    )
    def test_retryable_errors_cover_exhausted_transient_failures(self, _name: str, error_msg: str) -> None:
        # fetch_page already retries these with backoff; once that budget exhausts they must
        # stay classified as retryable (self-recovering via Temporal) rather than tracked
        # exception noise.
        assert error_message_matches(error_msg, self.source.get_retryable_errors())

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.validate_decagon_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        mock_validate.return_value = False
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is False
        assert message is not None

        mock_validate.assert_called_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DecagonResumeConfig

    # The second case guards the null-out: a watermark left over from an earlier
    # incremental configuration must not window a sync that is no longer incremental,
    # or the full refresh silently drops every row older than the stale watermark.
    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
            ("full_refresh_ignores_stale_watermark", False, datetime(2026, 1, 1, tzinfo=UTC), None),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.decagon_source")
    def test_source_for_pipeline_passes_arguments(
        self,
        _name: str,
        should_use_incremental_field: bool,
        last_value: datetime,
        expected_last_value: datetime | None,
        mock_decagon_source: mock.MagicMock,
    ) -> None:
        inputs = _make_inputs(
            schema_name="conversations",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="updated_at",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_decagon_source.call_args
        assert kwargs["api_key"] == self.config.api_key
        assert kwargs["endpoint"] == "conversations"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
        assert kwargs["incremental_field"] == "updated_at"
