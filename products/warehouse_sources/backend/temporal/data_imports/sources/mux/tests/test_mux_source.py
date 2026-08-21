from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mux import MuxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mux import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import ENDPOINTS, MUX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.source import MuxSource


def _config() -> MuxSourceConfig:
    return MuxSourceConfig(access_token_id="my-token-id", secret_key="my-secret")


class TestMuxSchemas:
    def test_get_schemas_incremental_matches_endpoint_config(self) -> None:
        # Only video views expose a server-side timestamp filter, so it's the one incremental table;
        # append is never offered because the incremental overlap needs merge-dedupe. This guards the
        # regression where every endpoint was reported as full refresh.
        schemas = {s.name: s for s in MuxSource().get_schemas(_config(), team_id=1)}
        for name, schema in schemas.items():
            assert schema.supports_incremental is MUX_ENDPOINTS[name].supports_incremental
            assert schema.supports_append is False
        assert schemas["video_views"].supports_incremental is True
        assert [f["field"] for f in schemas["video_views"].incremental_fields] == ["view_end"]
        assert schemas["assets"].supports_incremental is False
        assert schemas["assets"].incremental_fields == []


class TestMuxValidateCredentials:
    @parameterized.expand(
        [
            ("ok_no_schema", 200, None, True),
            ("ok_with_schema", 200, "assets", True),
            ("unauthorized_no_schema", 401, None, False),
            ("unauthorized_with_schema", 401, "assets", False),
            # 403 at source-create is accepted (token genuine, scope intentionally narrow)...
            ("forbidden_source_create", 403, None, True),
            # ...but rejected when validating a specific schema the user picked.
            ("forbidden_with_schema", 403, "assets", False),
            ("transport_error", None, None, False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: Optional[int], schema_name: Optional[str], expected_ok: bool
    ) -> None:
        # patch (not the monkeypatch fixture) because parameterized.expand can't inject pytest fixtures.
        with patch.object(source_module, "get_validation_status", return_value=status):
            ok, _msg = MuxSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_validate_credentials_uses_endpoint_path_for_known_schema(self, monkeypatch: Any) -> None:
        captured: dict[str, str] = {}

        def fake_status(access_token_id: str, secret_key: str, path: str) -> int:
            captured["path"] = path
            return 200

        monkeypatch.setattr(source_module, "get_validation_status", fake_status)
        MuxSource().validate_credentials(_config(), team_id=1, schema_name="signing_keys")
        assert captured["path"] == "/system/v1/signing-keys"


class TestMuxResumableWiring:
    def test_source_for_pipeline_plumbs_config_and_schema(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = MagicMock()

        def fake_mux_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "mux_source", fake_mux_source)

        inputs = MagicMock()
        inputs.schema_name = "video_views"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2023-01-01T00:00:00Z"
        manager = MagicMock()
        result = MuxSource().source_for_pipeline(_config(), manager, inputs)

        assert result is sentinel
        assert captured["access_token_id"] == "my-token-id"
        assert captured["secret_key"] == "my-secret"
        assert captured["endpoint"] == "video_views"
        assert captured["resumable_source_manager"] is manager
        # Incremental context must reach the transport so it can build the `timeframe[]` lower bound.
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2023-01-01T00:00:00Z"


class TestMuxCanonicalDescriptions:
    def test_canonical_descriptions_cover_declared_endpoints(self) -> None:
        descriptions = MuxSource().get_canonical_descriptions()
        # Every endpoint we expose should have a curated description so the warehouse can describe it
        # deterministically rather than paying an LLM per team.
        assert set(descriptions.keys()) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            assert entry.get("description")
            columns = entry.get("columns", {})
            # Every primary-key column must be documented so joins/keys are self-describing.
            for pk in MUX_ENDPOINTS[endpoint].primary_keys:
                assert columns.get(pk), f"{endpoint} missing '{pk}' column description"
