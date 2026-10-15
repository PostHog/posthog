from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import FLY_IO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.source import FlyIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flyio import FlyIoSourceConfig


def _config() -> FlyIoSourceConfig:
    return FlyIoSourceConfig(api_token="FlyV1 secret", organization_slug="acme")


class TestSourceConfig:
    def test_org_slug_requires_credential_reentry(self) -> None:
        # Changing which org the token points at must re-require the token, so a preserved token
        # can't be retargeted at another org it happens to reach.
        assert FlyIoSource().connection_host_fields == ["organization_slug"]


class TestGetSchemas:
    @parameterized.expand(
        [("machine_events", "machine_id"), ("machine_versions", "machine_id"), ("volume_snapshots", "volume_id")]
    )
    def test_fanout_children_key_on_their_app_and_parent(self, endpoint: str, parent_column: str) -> None:
        schema = FlyIoSource().get_schemas(_config(), team_id=1, names=[endpoint])[0]
        assert schema.detected_primary_keys is not None
        assert {"app_name", parent_column} <= set(schema.detected_primary_keys)
        assert {"app_name", parent_column} <= set(
            FLY_IO_ENDPOINTS[endpoint].fanout.parent_fields.values()  # type: ignore[union-attr]
        )


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.machines.dev/v1/orgs/acme/machines"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.machines.dev/v1/apps?org_slug=acme"),
            # A 400 on the org-scoped machines/volumes endpoint is a permanent rejection (auth passed,
            # since a bad token is a 401/403); retrying resends the same doomed request.
            (
                "bad_request",
                "400 Client Error: Bad Request for url: https://api.machines.dev/v1/orgs/acme/machines?limit=1000",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FlyIoSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.machines.dev', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.machines.dev/v1/apps"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FlyIoSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)
