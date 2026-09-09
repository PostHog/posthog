from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.settings import (
    DEEPSOURCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.source import DeepsourceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepsource import (
    DeepsourceSourceConfig,
)

_CONFIG = DeepsourceSourceConfig(api_token="tok", account_login="acme", vcs_provider="GITHUB")


def _source_inputs(schema_name: str) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    return inputs


class TestDeepsourceSource:
    def test_connection_host_fields_force_secret_reentry_on_account_change(self) -> None:
        # Changing account_login/vcs_provider retargets the stored PAT at another account, so
        # both must be host fields — the update serializer then demands the PAT be re-entered.
        assert DeepsourceSource().connection_host_fields == ["account_login", "vcs_provider"]

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = DeepsourceSource().get_schemas(_CONFIG, team_id=1)

        assert [s.name for s in schemas] == list(ENDPOINTS)
        # The API has no server-side timestamp filters, so nothing may advertise incremental.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = DeepsourceSource().get_schemas(_CONFIG, team_id=1, names=["repositories", "reports"])
        assert {s.name for s in schemas} == {"repositories", "reports"}

    def test_get_documented_tables_renders_static_catalog(self) -> None:
        source = DeepsourceSource()
        assert source.lists_tables_without_credentials

        tables = source.get_documented_tables()

        assert [t["name"] for t in tables] == list(ENDPOINTS)
        # Canonical descriptions must cover every endpoint so the public docs aren't thin.
        assert all(t["description"] for t in tables)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_wires_endpoint_config(self, endpoint: str) -> None:
        response = DeepsourceSource().source_for_pipeline(_CONFIG, MagicMock(), _source_inputs(endpoint))

        assert response.name == endpoint
        assert response.primary_keys == DEEPSOURCE_ENDPOINTS[endpoint].primary_keys
        assert callable(response.items)


class TestDeepsourceNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "auth_401",
                "401 Client Error: Unauthorized for url: https://api.deepsource.com/graphql/ (DeepSource API: Authentication required)",
            ),
            ("forbidden_403", "403 Client Error: Forbidden for url: https://api.deepsource.com/graphql/"),
            ("account_missing", "DeepSource account not found: 'acme' (GITHUB). Check the account login..."),
        ]
    )
    def test_non_retryable_errors_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = DeepsourceSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("transient_500", "DeepSource: server error 502"),
            ("rate_limited", "DeepSource: rate limited (429)"),
            ("graphql_error", "DeepSource GraphQL error: Something failed"),
            ("network", "DeepSource: transient network error - Read timed out. (read timeout=60)"),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = DeepsourceSource().get_non_retryable_errors()
        # Transient/server errors must stay retryable so the pipeline backs off and retries.
        assert not any(key in observed_error for key in non_retryable_errors)
