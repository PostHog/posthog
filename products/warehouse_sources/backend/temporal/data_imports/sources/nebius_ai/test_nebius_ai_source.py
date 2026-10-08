from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import NebiusAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.source import NebiusAISource


class TestNebiusAISchemas:
    def test_names_filter_narrows_the_list(self) -> None:
        schemas = NebiusAISource().get_schemas(MagicMock(), team_id=1, names=["files"])
        assert [s.name for s in schemas] == ["files"]


class TestNebiusAIValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Your Nebius AI API key is invalid or has expired.")),
            ("transient", (False, "Could not reach Nebius AI: boom")),
        ]
    )
    def test_validate_credentials_forwards_transport_result(self, _name: str, transport_result: tuple) -> None:
        # The source must forward the transport verdict verbatim so transient and permission messages
        # are not collapsed into a generic "invalid key".
        config = MagicMock()
        config.api_key = "nbk_test"
        with patch.object(source_module, "validate_nebius_ai_credentials", return_value=transport_result):
            assert NebiusAISource().validate_credentials(config, team_id=1) == transport_result


class TestNebiusAINonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.tokenfactory.nebius.com/v1/models"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.tokenfactory.nebius.com/v1/batches"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        errors = NebiusAISource().get_non_retryable_errors()
        assert any(key in observed_error for key in errors)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.tokenfactory.nebius.com/v1/files",
            ),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.tokenfactory.nebius.com"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed_error: str) -> None:
        errors = NebiusAISource().get_non_retryable_errors()
        assert not any(key in observed_error for key in errors)


class TestNebiusAIRegistration:
    def test_get_resumable_manager_namespace(self) -> None:
        # Sanity: the manager's data class survives a with_namespace() sibling (used for isolated state).
        inputs = MagicMock()
        manager = NebiusAISource().get_resumable_source_manager(inputs)
        assert manager.with_namespace("models")._data_class is NebiusAIResumeConfig
