from datetime import UTC, datetime

from parameterized import parameterized

from products.warehouse_sources.sources.render._config import RenderSourceConfig
from products.warehouse_sources.sources.render.source import RenderSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


class TestRenderSource:
    def setup_method(self) -> None:
        self.source = RenderSource()
        self.config = RenderSourceConfig(api_key="rnd_test", owner_id="tea-123")

    @parameterized.expand(
        [
            (
                "read_timeout",
                "HTTPSConnectionPool(host='api.render.com', port=443): Max retries exceeded with url: /v1/services?limit=100 "
                "(Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='api.render.com', port=443): "
                'Read timed out. (read timeout=60)"))',
            ),
            (
                "connection_refused",
                "HTTPSConnectionPool(host='api.render.com', port=443): Max retries exceeded with url: /v1/services?limit=100 "
                "(Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at 0x7f0000000000>: "
                "Failed to establish a new connection: [Errno 111] Connection refused'))",
            ),
        ]
    )
    def test_exhausted_connection_retries_are_retryable(self, _name: str, observed_error: str) -> None:
        assert any(pattern in observed_error for pattern in self.source.get_retryable_errors())
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            # Mutating resources with a server-side time filter sync incrementally via merge.
            ("services", True, False),
            ("deploys", True, False),
            # Events are immutable: append-only, never merge-incremental.
            ("events", False, True),
            # No usable watermark column: full refresh only.
            ("owners", False, False),
            ("environments", False, False),
            ("custom_domains", False, False),
        ]
    )
    def test_get_schemas_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        assert schema.supports_incremental == supports_incremental
        assert schema.supports_append == supports_append

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark leaking into a full refresh would silently skip older rows.
        result = SourceDriver(self.source, self.config).run(
            "services",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.requests[0].param("updatedAfter") is None
