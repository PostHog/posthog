from typing import Any, cast

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.dropbox_sign import (
    DropboxSignResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.source import DropboxSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DropboxSignSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str = "templates") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert DropboxSignSource().source_type == ExternalDataSourceType.DROPBOXSIGN

    def test_config_metadata(self) -> None:
        config = DropboxSignSource().get_source_config
        assert config.label == "Dropbox Sign"
        assert config.category == DataWarehouseSourceCategory.SALES
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Kept hidden while in alpha.
        assert config.unreleasedSource is True
        # docsUrl slug must match the posthog.com doc filename (kebab-case).
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dropbox-sign"

    def test_single_password_api_key_field(self) -> None:
        fields = DropboxSignSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True


class TestSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = DropboxSignSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = DropboxSignSource().get_schemas(MagicMock(), team_id=1, names=["templates"])
        assert [s.name for s in schemas] == ["templates"]

    def test_lists_tables_without_credentials_renders_documented_tables(self) -> None:
        # Static endpoint catalog (no I/O) opts the source into the public-docs table list.
        assert DropboxSignSource.lists_tables_without_credentials is True
        tables = DropboxSignSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == set(ENDPOINTS)
        sig = next(t for t in tables if t["name"] == "signature_requests")
        assert sig["sync_methods"] == ["Full refresh"]
        # Canonical descriptions flow through.
        assert sig["description"]


class TestValidateCredentials:
    def test_valid_key(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_dropbox_sign_credentials", lambda key: True)
        ok, err = DropboxSignSource().validate_credentials(DropboxSignSourceConfig(api_key="k"), team_id=1)
        assert ok is True
        assert err is None

    def test_invalid_key(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_dropbox_sign_credentials", lambda key: False)
        ok, err = DropboxSignSource().validate_credentials(DropboxSignSourceConfig(api_key="k"), team_id=1)
        assert ok is False
        assert err == "Invalid Dropbox Sign API key"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.hellosign.com/v3/account",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.hellosign.com/v3/template/list?page=1",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = DropboxSignSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.hellosign.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.hellosign.com/v3/account"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.hellosign.com/v3/account"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = DropboxSignSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = DropboxSignSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DropboxSignResumeConfig


class TestSourceForPipeline:
    def test_passes_schema_name_and_credentials_through(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "dropbox_sign_source", fake_source)

        manager = MagicMock()
        result = DropboxSignSource().source_for_pipeline(
            DropboxSignSourceConfig(api_key="my-key"),
            manager,
            _inputs(schema_name="signature_requests"),
        )

        assert cast(Any, result) == "response"
        assert captured["api_key"] == "my-key"
        assert captured["endpoint"] == "signature_requests"
        assert captured["resumable_source_manager"] is manager
