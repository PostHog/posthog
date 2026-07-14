from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.replicate import ReplicateResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.source import ReplicateSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "r8_test") -> MagicMock:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestReplicateSource:
    def test_source_type(self) -> None:
        assert ReplicateSource().source_type == ExternalDataSourceType.REPLICATE

    def test_source_config_has_password_api_key_field(self) -> None:
        config = ReplicateSource().get_source_config
        api_key_field = next(f for f in config.fields if getattr(f, "name", None) == "api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type.value == "password"
        assert api_key_field.required is True

    @parameterized.expand(
        [
            # (endpoint, supports_incremental, should_sync_default, primary_keys)
            ("predictions", True, True, ["id"]),
            ("trainings", False, True, ["id"]),
            ("deployments", False, True, ["owner", "name"]),
            ("models", False, False, ["owner", "name"]),
            ("hardware", False, True, ["sku"]),
            ("account", False, True, ["username"]),
        ]
    )
    def test_get_schemas(
        self, endpoint: str, supports_incremental: bool, should_sync_default: bool, primary_keys: list[str]
    ) -> None:
        # Only predictions has a server-side timestamp filter, so it's the only incremental endpoint;
        # marking any other incremental would fetch every page each run while pretending otherwise.
        schemas = {s.name: s for s in ReplicateSource().get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.should_sync_default is should_sync_default
        # Merge keys must survive into the schema, otherwise default-created tables lose their
        # dedupe metadata and incremental syncs would append duplicates.
        assert schema.detected_primary_keys == primary_keys
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = ReplicateSource().get_schemas(_config(), team_id=1, names=["predictions"])
        assert [s.name for s in schemas] == ["predictions"]

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Replicate API token")])
    def test_validate_credentials(self, _name: str, api_ok: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.replicate.source.validate_replicate_credentials",
            return_value=api_ok,
        ):
            ok, msg = ReplicateSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.replicate.com/v1/predictions", True),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.replicate.com/v1/account", True),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.replicate.com/v1/predictions",
                False,
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.replicate.com/v1/trainings",
                False,
            ),
        ]
    )
    def test_non_retryable_errors(self, _name: str, observed: str, is_non_retryable: bool) -> None:
        keys = ReplicateSource().get_non_retryable_errors()
        assert any(k in observed for k in keys) is is_non_retryable

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = ReplicateSource().get_resumable_source_manager(inputs)
        assert manager._data_class is ReplicateResumeConfig

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        # When should_use_incremental_field is False the last-value must not leak into the request,
        # otherwise a full refresh would silently filter by a stale cursor.
        inputs = MagicMock()
        inputs.schema_name = "predictions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00Z"
        inputs.incremental_field = "created_at"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.replicate.source.replicate_source"
        ) as mock_source:
            ReplicateSource().source_for_pipeline(_config(), MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials must yield the public-docs table catalog (SourceTables).
        tables = {t["name"]: t for t in ReplicateSource().get_documented_tables()}
        assert set(tables) == {"predictions", "trainings", "deployments", "models", "hardware", "account"}
        assert "Incremental" in tables["predictions"]["sync_methods"]
        assert "Incremental" not in tables["trainings"]["sync_methods"]
