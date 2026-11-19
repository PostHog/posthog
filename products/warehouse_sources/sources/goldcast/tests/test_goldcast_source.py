from products.warehouse_sources.sources.goldcast._config import GoldcastSourceConfig
from products.warehouse_sources.sources.goldcast.canonical_descriptions import CANONICAL_DESCRIPTIONS
from products.warehouse_sources.sources.goldcast.settings import ENDPOINTS
from products.warehouse_sources.sources.goldcast.source import GoldcastSource
from products.warehouse_sources.sources.sdk import SourceFieldInputConfig
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestSourceConfig:
    def test_single_secret_token_field(self) -> None:
        fields = {f.name: f for f in GoldcastSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"access_key"}
        assert fields["access_key"].required is True
        # The token is a credential, so it must be stored as a secret password field.
        assert fields["access_key"].secret is True


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
