from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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


class TestMem0SourceCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert Mem0Source().validate_credentials(_config(), team_id=1) == (True, None)

        assert network.requests_log[0].path == "/v1/ping/"
        assert network.requests_log[0].headers["authorization"] == "Token m0-test"


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
