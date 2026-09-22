from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mem0 import Mem0SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENDPOINTS,
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_API_VERSION_V3,
    MEMORIES_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source import Mem0Source

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source"


def _config(api_key: str = "m0-test", org_id: str | None = None, project_id: str | None = None) -> Mem0SourceConfig:
    return Mem0SourceConfig(api_key=api_key, org_id=org_id, project_id=project_id)


class TestMem0SourceConfig:
    def test_docs_url_matches_the_doc_slug(self):
        # The website derives the doc slug from docsUrl; a mismatch 404s the docs link.
        assert Mem0Source().get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/mem0"


class TestMem0SourceSchemas:
    def test_lists_every_endpoint(self):
        schemas = Mem0Source().get_schemas(_config(), team_id=1)

        assert [s.name for s in schemas] == list(ENDPOINTS)

    def test_only_memories_supports_incremental_and_never_append(self):
        schemas = {s.name: s for s in Mem0Source().get_schemas(_config(), team_id=1)}

        assert schemas[MEMORIES_ENDPOINT].supports_incremental is True
        assert {f["field"] for f in schemas[MEMORIES_ENDPOINT].incremental_fields} == {"updated_at", "created_at"}
        # Incremental pulls re-fetch updated rows; append mode would duplicate them.
        assert all(s.supports_append is False for s in schemas.values())
        # Entities and events expose no server-side timestamp filter — full refresh only.
        assert schemas[ENTITIES_ENDPOINT].supports_incremental is False
        assert schemas[EVENTS_ENDPOINT].supports_incremental is False

    def test_events_is_opt_in(self):
        schemas = {s.name: s for s in Mem0Source().get_schemas(_config(), team_id=1)}

        assert schemas[EVENTS_ENDPOINT].should_sync_default is False
        assert schemas[MEMORIES_ENDPOINT].should_sync_default is True

    def test_filters_by_names_argument(self):
        schemas = Mem0Source().get_schemas(_config(), team_id=1, names=[MEMORIES_ENDPOINT])

        assert [s.name for s in schemas] == [MEMORIES_ENDPOINT]

    def test_documented_tables_render_without_credentials(self):
        # Feeds the public docs' Supported tables section via lists_tables_without_credentials.
        tables = {t["name"]: t for t in Mem0Source().get_documented_tables()}

        assert set(tables) == set(ENDPOINTS)
        assert tables[MEMORIES_ENDPOINT]["description"]
        assert "Incremental" in tables[MEMORIES_ENDPOINT]["sync_methods"]


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

    def test_v1_is_deprecated_without_sunset_and_v3_is_not(self):
        # The in-product deprecation banner and the repin migration both key off this metadata; the
        # registry invariant test only checks generic relationships, not the v1-deprecated/v3-current
        # split or the (absent) sunset date this PR pins.
        source = Mem0Source()

        deprecation = source.get_version_deprecation(UNVERSIONED_API_VERSION)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert source.get_version_deprecation(MEM0_API_VERSION_V3) is None


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
    def test_plumbs_credentials_scoping_and_incremental_state(self, mock_source):
        inputs = MagicMock()
        inputs.schema_name = MEMORIES_ENDPOINT
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01"
        inputs.incremental_field = "updated_at"
        manager = MagicMock()

        Mem0Source().source_for_pipeline(_config("key", org_id="org_1", project_id="proj_1"), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == MEMORIES_ENDPOINT
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01"
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["org_id"] == "org_1"
        assert kwargs["project_id"] == "proj_1"

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
