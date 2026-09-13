from unittest.mock import MagicMock, patch

from parameterized import parameterized

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

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(spec=E2BSourceConfig), team_id=self.team_id, names=["templates"])
        assert [s.name for s in schemas] == ["templates"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid E2B API key"))])
    def test_validate_credentials_delegates_to_transport(self, _name: str, transport_ok: bool, expected) -> None:
        config = E2BSourceConfig(api_key="e2b_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials",
            return_value=transport_ok,
        ):
            assert self.source.validate_credentials(config, self.team_id) == expected

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
