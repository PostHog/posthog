from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur import MailosaurResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source import MailosaurSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert MailosaurSource().source_type == ExternalDataSourceType.MAILOSAUR

    def test_config_metadata(self) -> None:
        config = MailosaurSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Ships hidden while it's an unreleased alpha connector.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/mailosaur"

    def test_api_key_field_is_required_secret(self) -> None:
        fields = {
            f.name: f for f in MailosaurSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)
        }
        assert set(fields) == {"api_key"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True


class TestGetSchemas:
    def test_incremental_only_where_server_filter_exists(self) -> None:
        schemas = {s.name: s for s in MailosaurSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Only messages exposes a server-side `receivedAfter` filter, so it's the only incremental table.
        assert schemas["messages"].supports_incremental is True
        assert [f["field"] for f in schemas["messages"].incremental_fields] == ["received"]
        assert schemas["servers"].supports_incremental is False
        assert schemas["usage_transactions"].supports_incremental is False

    def test_messages_primary_key_is_composite(self) -> None:
        # Message summaries omit the server, so the key must include the injected parent id to stay
        # unique table-wide across the fan-out.
        schemas = {s.name: s for s in MailosaurSource().get_schemas(_config(), team_id=1)}
        assert schemas["messages"].detected_primary_keys == ["server", "id"]

    def test_names_filter(self) -> None:
        schemas = MailosaurSource().get_schemas(_config(), team_id=1, names=["servers"])
        assert {s.name for s in schemas} == {"servers"}

    def test_documented_tables_render_without_credentials(self) -> None:
        assert MailosaurSource.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in MailosaurSource().get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["messages"]["sync_methods"]
        assert tables["servers"]["sync_methods"] == ["Full refresh"]


class TestValidateCredentials:
    @parameterized.expand([("ok", True, None), ("bad", False, "Invalid Mailosaur API key")])
    def test_delegates_to_transport(self, _name: str, ok: bool, error: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source.validate_mailosaur_credentials",
            return_value=(ok, error),
        ) as mocked:
            result = MailosaurSource().validate_credentials(_config("abc"), team_id=1)
        assert result == (ok, error)
        mocked.assert_called_once_with("abc")


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = MailosaurSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MailosaurResumeConfig

    def test_source_for_pipeline_passes_incremental_value_only_when_enabled(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "messages"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source.mailosaur_source"
        ) as mocked:
            MailosaurSource().source_for_pipeline(_config(), manager, inputs)
        mocked.assert_called_once_with(
            api_key="key",
            endpoint="messages",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "servers"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source.mailosaur_source"
        ) as mocked:
            MailosaurSource().source_for_pipeline(_config(), MagicMock(), inputs)
        # A full-refresh table must not carry a stale cursor into the request.
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://mailosaur.com/api/servers", True),
            ("forbidden", "403 Client Error: Forbidden for url: https://mailosaur.com/api/messages", True),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://mailosaur.com/api/messages", False),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://mailosaur.com/api/servers",
                False,
            ),
        ]
    )
    def test_only_credential_errors_are_non_retryable(self, _name: str, observed: str, should_match: bool) -> None:
        non_retryable = MailosaurSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable) is should_match


class TestCanonicalDescriptions:
    def test_keys_are_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_source_exposes_canonical_descriptions(self) -> None:
        assert MailosaurSource().get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
