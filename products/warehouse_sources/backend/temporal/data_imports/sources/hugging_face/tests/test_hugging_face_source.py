from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

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

    def test_source_config_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_token", "author"}
        # The token is a secret; the namespace is a plain text scope.
        assert fields["api_token"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_token"].secret is True
        assert fields["api_token"].required is True
        assert fields["author"].type == SourceFieldInputConfigType.TEXT
        assert fields["author"].secret is False
        assert fields["author"].required is True

    def test_connection_host_fields_force_secret_reentry_on_author_change(self) -> None:
        # Changing author retargets the stored token at another namespace, so it must count as a host field.
        assert self.source.connection_host_fields == ["author"]

    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    def test_get_schemas_are_full_refresh_only(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert endpoint in schemas
        # The Hub has no server-side timestamp filter, so incremental/append must be off.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []

    def test_validate_credentials_success(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None
