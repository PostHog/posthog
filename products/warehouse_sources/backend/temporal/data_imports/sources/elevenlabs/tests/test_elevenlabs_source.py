from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source import ElevenLabsSource


class TestElevenLabsSchemas:
    @parameterized.expand(
        [
            # history/conversations have real server-side time filters; agents/voices do not.
            ("history", True, True),
            ("conversations", True, False),
            ("agents", False, False),
            ("voices", False, False),
        ]
    )
    def test_schema_sync_capabilities(self, endpoint: str, incremental: bool, append: bool) -> None:
        # Marking conversations appendable would materialize post-call mutations (status/summary) as
        # duplicate rows; marking agents/voices incremental would break sync (no filter to honor).
        schemas = {s.name: s for s in ElevenLabsSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append

    def test_incremental_fields_are_unix_integers(self) -> None:
        schemas = {s.name: s for s in ElevenLabsSource().get_schemas(MagicMock(), team_id=1)}
        history = schemas["history"]
        assert [f["field"] for f in history.incremental_fields] == ["date_unix"]

    def test_names_filter_limits_returned_schemas(self) -> None:
        schemas = ElevenLabsSource().get_schemas(MagicMock(), team_id=1, names=["voices"])
        assert [s.name for s in schemas] == ["voices"]
