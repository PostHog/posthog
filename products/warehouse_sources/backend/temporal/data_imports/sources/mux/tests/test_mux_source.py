from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MuxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mux import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import MuxResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.source import MuxSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MuxSourceConfig:
    return MuxSourceConfig(access_token_id="my-token-id", secret_key="my-secret")


class TestMuxSourceConfig:
    def test_source_type(self) -> None:
        assert MuxSource().source_type == ExternalDataSourceType.MUX

    def test_source_config_fields(self) -> None:
        config = MuxSource().get_source_config
        assert config.name.value == "Mux"
        field_names = {f.name for f in config.fields}
        assert field_names == {"access_token_id", "secret_key"}

    def test_secret_key_is_marked_secret(self) -> None:
        fields = {f.name: f for f in MuxSource().get_source_config.fields}
        secret_field, token_field = fields["secret_key"], fields["access_token_id"]
        # Narrow the FieldType union so `.secret` is statically visible.
        assert isinstance(secret_field, SourceFieldInputConfig)
        assert isinstance(token_field, SourceFieldInputConfig)
        assert secret_field.secret is True
        assert token_field.secret is False


class TestMuxSchemas:
    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = MuxSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = MuxSource().get_schemas(_config(), team_id=1, names=["assets"])
        assert [s.name for s in schemas] == ["assets"]


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


class TestMuxNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.mux.com/video/v1/assets?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.mux.com/system/v1/signing-keys?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = MuxSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.mux.com/video/v1/assets"),
            ("read_timeout", "HTTPSConnectionPool(host='api.mux.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = MuxSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestMuxResumableWiring:
    def test_get_resumable_source_manager_binds_to_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = MuxSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MuxResumeConfig

    def test_source_for_pipeline_plumbs_config_and_schema(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = MagicMock()

        def fake_mux_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "mux_source", fake_mux_source)

        inputs = MagicMock()
        inputs.schema_name = "assets"
        manager = MagicMock()
        result = MuxSource().source_for_pipeline(_config(), manager, inputs)

        assert result is sentinel
        assert captured["access_token_id"] == "my-token-id"
        assert captured["secret_key"] == "my-secret"
        assert captured["endpoint"] == "assets"
        assert captured["resumable_source_manager"] is manager


class TestMuxCanonicalDescriptions:
    def test_canonical_descriptions_cover_declared_endpoints(self) -> None:
        descriptions = MuxSource().get_canonical_descriptions()
        # Every endpoint we expose should have a curated description so the warehouse can describe it
        # deterministically rather than paying an LLM per team.
        assert set(descriptions.keys()) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            assert entry.get("description")
            assert entry.get("columns", {}).get("id"), f"{endpoint} missing id column description"
