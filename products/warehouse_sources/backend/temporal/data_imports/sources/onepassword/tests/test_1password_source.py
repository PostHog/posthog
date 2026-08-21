from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepassword import (
    OnePasswordSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.source import OnePasswordSource

ALL_FEATURES_INTROSPECTION = {
    "uuid": "OK41XEGLRTH4YKO5YRTCPNX3IU",
    "features": ["auditevents", "itemusages", "signinattempts"],
}


class TestOnePasswordSource:
    def setup_method(self) -> None:
        self.source = OnePasswordSource()

    @parameterized.expand(
        [
            ("valid_token", ALL_FEATURES_INTROSPECTION, None, True),
            ("invalid_token", None, None, False),
            ("scoped_schema_with_feature", ALL_FEATURES_INTROSPECTION, "audit_events", True),
            ("scoped_schema_missing_feature", {"features": ["itemusages"]}, "audit_events", False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, introspection: dict | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value=introspection):
            ok, error = self.source.validate_credentials(config, team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_endpoint_permissions_report_missing_features(self) -> None:
        # A token scoped to a subset of features must surface which tables it can't read so the
        # schema picker can flag them — without blocking the reachable ones.
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value={"features": ["signinattempts"]}):
            permissions = self.source.get_endpoint_permissions(config, team_id=1, endpoints=list(ENDPOINTS))
        assert permissions["sign_in_attempts"] is None
        assert permissions["item_usages"] is not None
        assert permissions["audit_events"] is not None

    def test_endpoint_permissions_never_block_on_probe_failure(self) -> None:
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value=None):
            permissions = self.source.get_endpoint_permissions(config, team_id=1, endpoints=list(ENDPOINTS))
        assert all(reason is None for reason in permissions.values())
