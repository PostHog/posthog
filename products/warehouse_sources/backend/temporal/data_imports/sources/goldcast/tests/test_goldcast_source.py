from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.goldcast import (
    GoldcastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.source import GoldcastSource


class TestSourceConfig:
    def test_single_secret_token_field(self) -> None:
        fields = {f.name: f for f in GoldcastSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"access_key"}
        assert fields["access_key"].required is True
        # The token is a credential, so it must be stored as a secret password field.
        assert fields["access_key"].secret is True


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://customapi.goldcast.io/event/",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://customapi.goldcast.io/core/organization/",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = GoldcastSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='customapi.goldcast.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://customapi.goldcast.io/event/"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = GoldcastSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)


class TestValidateCredentials:
    def test_valid_token_passes(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": "org"})]):
            assert GoldcastSource().validate_credentials(GoldcastSourceConfig(access_key="tok"), team_id=1) == (
                True,
                None,
            )


class TestDocumentedTables:
    def test_canonical_descriptions_key_on_endpoint_names(self) -> None:
        # Canonical descriptions must key on schema/endpoint names so enrichment applies them.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
