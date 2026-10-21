from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source import ElevenLabsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.elevenlabs import (
    ElevenLabsSourceConfig,
)


class TestElevenLabsSchemas:
    @parameterized.expand(
        [
            # history/conversations have real server-side time filters; agents/voices do not.
            ("history", True, True),
            ("conversations", True, False),
            ("agents", False, False),
            ("voices", False, False),
            ("triage_tickets", False, False),
            ("models", False, False),
            ("workspace_members", False, False),
            ("workspace_groups", False, False),
            ("tools", False, False),
            # Executions take a server-side `start_time` filter, so they merge incrementally.
            ("tool_executions", True, False),
            ("phone_numbers", False, False),
            ("batch_calls", False, False),
            ("subscription", False, False),
        ]
    )
    def test_schema_sync_capabilities(self, endpoint: str, incremental: bool, append: bool) -> None:
        # Marking conversations appendable would materialize post-call mutations (status/summary) as
        # duplicate rows; marking agents/voices incremental would break sync (no filter to honor).
        schemas = {s.name: s for s in ElevenLabsSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append


class TestElevenLabsPipelinePlumbing:
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # When incremental is off, the stored watermark must not leak into the request as a filter.
        result = SourceDriver(ElevenLabsSource(), ElevenLabsSourceConfig(api_key="sk_test")).run(
            "history",
            [ScriptedResponse(json={"history": [], "has_more": False})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("date_after_unix") == [None]
