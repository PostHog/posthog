from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.source import FireworksAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fireworksai import (
    FireworksAISourceConfig,
)


def _config(api_key: str = "fw_test", account_id: str = "my-account") -> FireworksAISourceConfig:
    return FireworksAISourceConfig(api_key=api_key, account_id=account_id)


class TestSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert FireworksAISource.lists_tables_without_credentials is True

    def test_account_id_change_requires_secret_reentry(self) -> None:
        # Dropping this override would let an editor retarget a preserved API key at another
        # Fireworks account without re-entering it (the update serializer keys off this list).
        assert FireworksAISource().connection_host_fields == ["account_id"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("account_not_found", 404, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_schema_is_rejected", 403, "models", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, _err = FireworksAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert network.requests_log

    def test_invalid_account_id_rejected_without_probe(self) -> None:
        with scripted_network([]) as network:
            ok, err = FireworksAISource().validate_credentials(_config(account_id="bad id!"), team_id=1)
        assert ok is False
        assert err is not None
        assert network.requests_log == []

    def test_pasted_resource_prefix_is_normalized_before_probe(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            ok, _err = FireworksAISource().validate_credentials(_config(account_id="accounts/my-account"), team_id=1)
        assert ok is True
        assert network.requests_log[0].path == "/v1/accounts/my-account/models"
        assert network.requests_log[0].headers["authorization"] == "Bearer fw_test"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "account_not_found",
                "404 Client Error: Not Found for url: https://api.fireworks.ai/v1/accounts/nope/models",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FireworksAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)
