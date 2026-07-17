from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HuggingFaceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face import (
    HuggingFaceResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.source import HuggingFaceSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> HuggingFaceSourceConfig:
    return HuggingFaceSourceConfig(api_token="hf_token", author="acme")


class TestHuggingFaceSourceClass:
    def setup_method(self) -> None:
        self.source = HuggingFaceSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HUGGINGFACE

    def test_source_config_identity(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Hugging Face"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hugging-face"

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

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["datasets"])
        assert [s.name for s in schemas] == ["datasets"]

    @parameterized.expand([("unauthorized", "401 Client Error"), ("forbidden", "403 Client Error")])
    def test_non_retryable_errors(self, _name: str, expected_key_prefix: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any(key.startswith(expected_key_prefix) for key in errors)

    def test_validate_credentials_success(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_hugging_face_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert manager._data_class is HuggingFaceResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "datasets"
        manager = MagicMock()
        with patch.object(source_module, "hugging_face_source") as mock_source:
            self.source.source_for_pipeline(_config(), manager, inputs)
        mock_source.assert_called_once_with(
            api_token="hf_token",
            endpoint="datasets",
            author="acme",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == {"models", "datasets", "spaces"}
        for table in descriptions.values():
            assert table["description"]
            assert "id" in table["columns"]
