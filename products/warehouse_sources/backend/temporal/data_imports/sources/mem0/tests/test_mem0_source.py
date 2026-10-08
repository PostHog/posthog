from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mem0 import Mem0SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEMORIES_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source import Mem0Source

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source"


def _config(api_key: str = "m0-test", org_id: str | None = None, project_id: str | None = None) -> Mem0SourceConfig:
    return Mem0SourceConfig(api_key=api_key, org_id=org_id, project_id=project_id)


class TestMem0SourceSchemas:
    def test_only_memories_supports_incremental_and_never_append(self):
        schemas = {s.name: s for s in Mem0Source().get_schemas(_config(), team_id=1)}

        assert schemas[MEMORIES_ENDPOINT].supports_incremental is True
        assert {f["field"] for f in schemas[MEMORIES_ENDPOINT].incremental_fields} == {"updated_at", "created_at"}
        # Incremental pulls re-fetch updated rows; append mode would duplicate them.
        assert all(s.supports_append is False for s in schemas.values())
        # Entities and events expose no server-side timestamp filter — full refresh only.
        assert schemas[ENTITIES_ENDPOINT].supports_incremental is False
        assert schemas[EVENTS_ENDPOINT].supports_incremental is False

    def test_filters_by_names_argument(self):
        schemas = Mem0Source().get_schemas(_config(), team_id=1, names=[MEMORIES_ENDPOINT])

        assert [s.name for s in schemas] == [MEMORIES_ENDPOINT]


class TestMem0SourceCredentials:
    @patch(f"{_SOURCE_MODULE}.validate_mem0_credentials", return_value=True)
    def test_valid_key(self, mock_validate):
        assert Mem0Source().validate_credentials(_config(), team_id=1) == (True, None)
        mock_validate.assert_called_once_with("m0-test")

    @patch(f"{_SOURCE_MODULE}.validate_mem0_credentials", return_value=False)
    def test_invalid_key_returns_actionable_error(self, mock_validate):
        ok, error = Mem0Source().validate_credentials(_config(), team_id=1)

        assert ok is False
        assert error == "Invalid Mem0 API key"


class TestMem0SourcePipeline:
    @patch(f"{_SOURCE_MODULE}.mem0_source")
    def test_incremental_flag_never_reaches_full_refresh_endpoints(self, mock_source):
        # Entities has no server-side timestamp filter; forwarding the incremental flag
        # would make the transport build a filter the endpoint can't honor.
        inputs = MagicMock()
        inputs.schema_name = ENTITIES_ENDPOINT
        inputs.should_use_incremental_field = True
        inputs.incremental_field = None

        Mem0Source().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["should_use_incremental_field"] is False
