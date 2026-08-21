from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.huggingface import (
    HuggingFaceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.source import HuggingFaceSource


def _config() -> HuggingFaceSourceConfig:
    return HuggingFaceSourceConfig(api_token="hf_token", author="acme")


class TestHuggingFaceSourceClass:
    def setup_method(self) -> None:
        self.source = HuggingFaceSource()
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None
