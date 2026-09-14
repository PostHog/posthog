from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.source import MailosaurSource


def _config(api_key: str = "key") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


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


class TestResumableWiring:
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "servers"
        inputs.team_id = 7
        inputs.job_id = "job-1"
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
