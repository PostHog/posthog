import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    INVALID_CREDENTIALS_ERROR,
    NO_ACCESS_ERROR,
    E2BConfigurationError,
    _require_team_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source import E2BSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.e2b import E2BSourceConfig


class TestE2BSource:
    def setup_method(self) -> None:
        self.source = E2BSource()
        self.team_id = 123

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # No E2B list endpoint has a server-side timestamp filter, so none may advertise incremental
        # or append — doing so would let the pipeline skip rows it never actually filtered server-side.
        schemas = self.source.get_schemas(MagicMock(spec=E2BSourceConfig), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

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

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(spec=E2BSourceConfig), team_id=self.team_id, names=["templates"])
        assert [s.name for s in schemas] == ["templates"]

    def test_a_table_needing_the_team_id_says_so_instead_of_probing(self) -> None:
        # The per-schema check is the only place a user learns the team ID is missing before the
        # sync fails, and a credential probe cannot tell them anything about it.
        config = E2BSourceConfig(api_key="e2b_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials"
        ) as probe:
            ok, message = self.source.validate_credentials(config, self.team_id, "team_metrics")
        assert ok is False
        assert message is not None and "team ID" in message
        probe.assert_not_called()

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, INVALID_CREDENTIALS_ERROR)),
            ("no_access", (False, NO_ACCESS_ERROR)),
        ]
    )
    def test_validate_credentials_delegates_to_transport(self, _name: str, transport_result) -> None:
        config = E2BSourceConfig(api_key="e2b_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials",
            return_value=transport_result,
        ):
            assert self.source.validate_credentials(config, self.team_id) == transport_result

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
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials",
            side_effect=Exception("upstream 503"),
        ):
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None and "invalid" not in message.lower()

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.e2b.app/v2/sandboxes?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.e2b.app/snapshots"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand([("missing", None), ("malformed", "../admin")])
    def test_a_bad_team_id_stops_the_sync_instead_of_retrying(self, _name: str, team_id: str | None) -> None:
        # Only a settings change can fix it, so the message the transport raises has to be one the
        # source classifies as non-retryable — otherwise the job burns every attempt.
        with pytest.raises(E2BConfigurationError) as exc:
            _require_team_id(team_id)
        assert str(exc.value) in self.source.get_non_retryable_errors()

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.e2b.app', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.e2b.app/v2/sandboxes"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_documented_tables_render_from_static_catalog(self) -> None:
        # lists_tables_without_credentials=True lets posthog.com render the Supported tables section
        # with no credentials; the canonical descriptions must feed through.
        assert self.source.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["sandboxes"]["description"]
        assert tables["sandboxes"]["sync_methods"] == ["Full refresh"]
