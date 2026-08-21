from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.source import LinkrunnerSource


class TestGetSchemas:
    @parameterized.expand(
        [
            # (endpoint, supports_incremental, primary_keys)
            ("campaigns", False, ["display_id"]),
            ("attributed_users", True, ["campaign_display_id", "user_id", "attributed_at"]),
            ("reporting_campaigns", False, ["display_id"]),
        ]
    )
    def test_schema_incremental_and_primary_keys(
        self, endpoint: str, supports_incremental: bool, primary_keys: list[str]
    ) -> None:
        schemas = {s.name: s for s in LinkrunnerSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        # Only attributed-users has a genuine server-side timestamp filter; the rest ship full refresh.
        assert schema.supports_incremental is supports_incremental
        assert schema.detected_primary_keys == primary_keys

    def test_names_filter_restricts_output(self) -> None:
        schemas = LinkrunnerSource().get_schemas(MagicMock(), team_id=1, names=["campaigns"])
        assert [s.name for s in schemas] == ["campaigns"]


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validation_maps_transport_result(self, _name: str, transport_ok: bool, expected: bool) -> None:
        config = MagicMock(api_key="key")
        with patch.object(source_module, "validate_linkrunner_credentials", return_value=transport_ok):
            ok, error = LinkrunnerSource().validate_credentials(config, team_id=1)
        assert ok is expected
        assert (error is None) is expected
