import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    INVALID_CREDENTIALS_ERROR,
    NO_ACCESS_ERROR,
    E2BConfigurationError,
    _require_team_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source import E2BSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.e2b import E2BSourceConfig


class TestE2BSource:
    def setup_method(self) -> None:
        self.source = E2BSource()
        self.team_id = 123

    @parameterized.expand(
        [
            # A table whose team ID is missing would fail its first sync, so it starts unselected.
            ("team_metrics_without_team_id", None, "team_metrics", False),
            ("team_metrics_with_team_id", "prj_1", "team_metrics", True),
            # One request per sandbox per sync is a cost to opt into, not a default.
            ("sandbox_metrics", "prj_1", "sandbox_metrics", False),
            ("sandboxes", None, "sandboxes", True),
        ]
    )
    def test_should_sync_default_per_endpoint(
        self, _name: str, team_id: str | None, endpoint: str, expected: bool
    ) -> None:
        config = E2BSourceConfig(api_key="e2b_test", team_id=team_id)
        schemas = {s.name: s for s in self.source.get_schemas(config, team_id=self.team_id)}
        assert schemas[endpoint].should_sync_default is expected

    def test_a_table_needing_the_team_id_says_so_instead_of_probing(self) -> None:
        # The per-schema check is the only place a user learns the team ID is missing before the
        # sync fails, and a credential probe cannot tell them anything about it.
        config = E2BSourceConfig(api_key="e2b_test")
        with scripted_network([]) as network:
            ok, message = self.source.validate_credentials(config, self.team_id, "team_metrics")
        assert ok is False
        assert message is not None and "team ID" in message
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, INVALID_CREDENTIALS_ERROR)),
            ("no_access", (False, NO_ACCESS_ERROR)),
        ]
    )
    def test_validate_credentials_delegates_to_transport(
        self, _name: str, transport_result: tuple[bool, str | None]
    ) -> None:
        config = E2BSourceConfig(api_key="e2b_test")
        status = 200 if transport_result[0] else 401 if transport_result[1] == INVALID_CREDENTIALS_ERROR else 403
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert self.source.validate_credentials(config, self.team_id) == transport_result
        assert network.requests_log[0].path == "/v2/sandboxes"

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.e2b.app", INVALID_CREDENTIALS_ERROR),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.e2b.app", NO_ACCESS_ERROR),
        ]
    )
    def test_a_rejected_key_reads_the_same_during_setup_and_during_a_sync(
        self, _name: str, error_key: str, expected: str
    ) -> None:
        # Setup and sync reach the message by different routes, so a divergence between them is
        # invisible unless the two are compared.
        assert self.source.get_non_retryable_errors()[error_key] == expected

    def test_validate_credentials_transient_error_is_not_reported_as_invalid(self) -> None:
        # A probe that can't reach E2B must not brand a possibly-valid key "invalid" and send the user
        # down the credential-reset path — the message has to point at retrying instead.
        config = E2BSourceConfig(api_key="e2b_test")
        with scripted_network([ConnectionResetError("connection reset")]):
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None and "invalid" not in message.lower()

    @parameterized.expand([("missing", None), ("malformed", "../admin")])
    def test_a_bad_team_id_stops_the_sync_instead_of_retrying(self, _name: str, team_id: str | None) -> None:
        # Only a settings change can fix it, so the message the transport raises has to be one the
        # source classifies as non-retryable — otherwise the job burns every attempt.
        with pytest.raises(E2BConfigurationError) as exc:
            _require_team_id(team_id)
        assert str(exc.value) in self.source.get_non_retryable_errors()
