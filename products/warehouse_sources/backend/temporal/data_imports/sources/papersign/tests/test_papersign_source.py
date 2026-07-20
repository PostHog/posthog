from typing import cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PapersignSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign import PapersignResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.source import PapersignSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_token: str = "tok") -> PapersignSourceConfig:
    return PapersignSourceConfig(api_token=api_token)


class TestPapersignSourceConfig:
    def test_source_type(self) -> None:
        assert PapersignSource().source_type == ExternalDataSourceType.PAPERSIGN

    def test_visible_and_alpha(self) -> None:
        cfg = PapersignSource().get_source_config
        assert cfg.unreleasedSource is None
        assert cfg.releaseStatus == ReleaseStatus.ALPHA
        assert cfg.category == DataWarehouseSourceCategory.SALES
        assert cfg.docsUrl == "https://posthog.com/docs/cdp/sources/papersign"

    def test_exposes_api_token_field(self) -> None:
        cfg = PapersignSource().get_source_config
        names = {f.name for f in cfg.fields}
        assert names == {"api_token"}

        api_token_field = next(f for f in cfg.fields if f.name == "api_token")
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.required is True
        assert api_token_field.secret is True
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD


class TestPapersignSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = {s.name: s for s in PapersignSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == ["id"]

    def test_names_filter_subsets_schemas(self) -> None:
        schemas = PapersignSource().get_schemas(_config(), team_id=1, names=["documents"])
        assert [s.name for s in schemas] == ["documents"]

    def test_lists_tables_without_credentials_for_docs(self) -> None:
        source = PapersignSource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        for table in tables:
            assert table["sync_methods"] == ["Full refresh"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = PapersignSource().get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)


class TestPapersignCredentials:
    @patch.object(source_module, "validate_papersign_credentials", return_value=(True, None))
    def test_delegates_to_transport(self, mock_validate: MagicMock) -> None:
        ok, error = PapersignSource().validate_credentials(_config(api_token="abc"), team_id=1)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("abc")

    @patch.object(source_module, "validate_papersign_credentials", return_value=(False, "Invalid Paperform API key."))
    def test_propagates_failure(self, _mock_validate: MagicMock) -> None:
        ok, error = PapersignSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "Invalid Paperform API key."


class TestPapersignNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.paperform.co/v1/papersign/documents"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.paperform.co/v1/papersign/spaces"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = PapersignSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.paperform.co/v1/papersign/documents",
            ),
            (
                "rate_limit",
                "429 Client Error: Too Many Requests for url: https://api.paperform.co/v1/papersign/folders",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = PapersignSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestPapersignPipelineWiring:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = PapersignSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PapersignResumeConfig

    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        captured: dict[str, object] = {}

        def fake_source(**kwargs: object) -> object:
            captured.update(kwargs)
            return "sentinel"

        inputs = MagicMock()
        inputs.schema_name = "documents"
        manager = MagicMock()
        logger = MagicMock()
        inputs.logger = logger

        with patch.object(source_module, "papersign_source", side_effect=fake_source) as mock_source:
            result = PapersignSource().source_for_pipeline(_config(api_token="abc"), manager, inputs)

        assert cast(object, result) == "sentinel"
        mock_source.assert_called_once()
        assert captured["api_token"] == "abc"
        assert captured["endpoint"] == "documents"
        assert captured["resumable_source_manager"] is manager
        assert captured["logger"] is logger
