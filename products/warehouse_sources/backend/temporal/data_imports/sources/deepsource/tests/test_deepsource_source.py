from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.settings import (
    DEEPSOURCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.source import DeepsourceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepsource import (
    DeepsourceSourceConfig,
)

_CONFIG = DeepsourceSourceConfig(api_token="tok", account_login="acme", vcs_provider="GITHUB")


class TestDeepsourceSource:
    def test_connection_host_fields_force_secret_reentry_on_account_change(self) -> None:
        # Changing account_login/vcs_provider retargets the stored PAT at another account, so
        # both must be host fields — the update serializer then demands the PAT be re-entered.
        assert DeepsourceSource().connection_host_fields == ["account_login", "vcs_provider"]

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_wires_endpoint_config(self, endpoint: str) -> None:
        connection = {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}
        if endpoint == "analyzers":
            payload = {"data": {"analyzers": connection}}
        else:
            payload = {"data": {"account": {"repositories": connection}}}
        result = SourceDriver(DeepsourceSource(), _CONFIG).run(endpoint, [ScriptedResponse(json=payload)])

        assert result.raised is None
        response = result.response
        assert response is not None
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
