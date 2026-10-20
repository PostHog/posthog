from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.source import DemodeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.demodesk import (
    DemodeskSourceConfig,
)


class TestDemodeskSourceValidateCredentials:
    def test_rejects_non_ascii_key_without_calling_the_api(self) -> None:
        config = DemodeskSourceConfig(api_key="key​with-invisible-char")
        with scripted_network([]) as network:
            is_valid, message = DemodeskSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "unsupported character" in message
        assert network.requests_log == []

    def test_forwards_ascii_key_to_the_api_probe(self) -> None:
        config = DemodeskSourceConfig(api_key="plain-key")
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert DemodeskSource().validate_credentials(config, team_id=1) == (True, None)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/v2/me"
        assert network.requests_log[0].headers["authorization"] == "Bearer plain-key"
