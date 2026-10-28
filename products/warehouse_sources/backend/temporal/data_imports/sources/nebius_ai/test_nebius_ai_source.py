from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import NebiusAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.source import NebiusAISource


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


class TestNebiusAIRegistration:
    def test_get_resumable_manager_namespace(self) -> None:
        # Sanity: the manager's data class survives a with_namespace() sibling (used for isolated state).
        inputs = MagicMock()
        manager = NebiusAISource().get_resumable_source_manager(inputs)
        assert manager.with_namespace("models")._data_class is NebiusAIResumeConfig
