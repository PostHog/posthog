from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.source import ReplicateSource


def _config(api_key: str = "r8_test") -> MagicMock:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestReplicateSource:
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

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Replicate API token")])
    def test_validate_credentials(self, _name: str, api_ok: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.replicate.source.validate_replicate_credentials",
            return_value=api_ok,
        ):
            ok, msg = ReplicateSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
