from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.source import CohereSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cohere import CohereSourceConfig


def _config() -> CohereSourceConfig:
    return CohereSourceConfig(api_key="test-key")


class TestCohereSourceClass:
    def setup_method(self) -> None:
        self.source = CohereSource()
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        with patch.object(source_module, "validate_cohere_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_cohere_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None
