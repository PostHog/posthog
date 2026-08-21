from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mem0 import Mem0SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import MEM0_API_VERSION_V3
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source import Mem0Source

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source"


def _config(api_key: str = "m0-test", org_id: str | None = None, project_id: str | None = None) -> Mem0SourceConfig:
    return Mem0SourceConfig(api_key=api_key, org_id=org_id, project_id=project_id)


class TestMem0SourceVersions:
    def test_supports_v1_and_v3_with_v3_default(self):
        # v3 is the memory API the source already reads and the new default for fresh sources; the
        # unversioned placeholder stays supported so existing pinned (or NULL) rows keep resolving
        # to their unchanged wire behaviour. Both labels resolve to the same requests.
        source = Mem0Source()

        assert source.supported_versions == (UNVERSIONED_API_VERSION, MEM0_API_VERSION_V3)
        assert source.default_version == MEM0_API_VERSION_V3
        assert source.resolve_api_version(None) == MEM0_API_VERSION_V3
        assert source.resolve_api_version(UNVERSIONED_API_VERSION) == UNVERSIONED_API_VERSION


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
