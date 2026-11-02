from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linkrunner import (
    LinkrunnerSourceConfig,
)
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


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validation_maps_transport_result(self, _name: str, transport_ok: bool, expected: bool) -> None:
        config = LinkrunnerSourceConfig(api_key="key")
        with scripted_network([ScriptedResponse(status=200 if transport_ok else 401)]) as network:
            ok, error = LinkrunnerSource().validate_credentials(config, team_id=1)
        assert ok is expected
        assert (error is None) is expected
        assert network.requests_log[0].path == "/api/v1/campaigns"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.linkrunner.io/api/v1/campaigns",
                True,
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.linkrunner.io/api/v1/attributed-users",
                True,
            ),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.linkrunner.io", False),
            ("timeout", "HTTPSConnectionPool(host='api.linkrunner.io', port=443): Read timed out.", False),
        ]
    )
    def test_only_credential_errors_are_non_retryable(self, _name: str, observed: str, expected: bool) -> None:
        non_retryable = LinkrunnerSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable) is expected
