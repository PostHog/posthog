import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey import ChurnkeyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source import ChurnkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChurnkeySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source.validate_churnkey_credentials"
)


def _config() -> ChurnkeySourceConfig:
    return ChurnkeySourceConfig.from_dict({"api_key": "data_key", "app_id": "app_123"})


def _inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="Sessions",
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


class TestChurnkeySourceConfig:
    def test_source_type(self) -> None:
        assert ChurnkeySource().source_type == ExternalDataSourceType.CHURNKEY

    def test_source_config_fields(self) -> None:
        config = ChurnkeySource().get_source_config
        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}

        assert set(fields) == {"api_key", "app_id"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        assert fields["app_id"].type == SourceFieldInputConfigType.TEXT
        assert fields["app_id"].secret is False

    def test_source_config_metadata(self) -> None:
        config = ChurnkeySource().get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/churnkey"

    def test_lists_tables_without_credentials(self) -> None:
        # Static catalog (no I/O), so the public docs can render the table list.
        assert ChurnkeySource.lists_tables_without_credentials is True

    def test_connection_host_fields_includes_app_id(self) -> None:
        # Changing app_id retargets where the stored API key is used, so editing it must
        # require re-entering the secret.
        assert ChurnkeySource().connection_host_fields == ["app_id"]


class TestChurnkeySchemas:
    def test_get_schemas(self) -> None:
        schemas = ChurnkeySource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert "Sessions" in names

        sessions = next(s for s in schemas if s.name == "Sessions")
        assert sessions.supports_incremental is False
        assert sessions.supports_append is False
        assert sessions.detected_primary_keys == ["_id"]

    def test_get_schemas_name_filter(self) -> None:
        schemas = ChurnkeySource().get_schemas(_config(), team_id=1, names=["does-not-exist"])
        assert schemas == []

    def test_canonical_descriptions_cover_sessions(self) -> None:
        canonical = ChurnkeySource().get_canonical_descriptions()
        assert "Sessions" in canonical
        assert "_id" in canonical["Sessions"]["columns"]

    def test_documented_tables_render(self) -> None:
        # Exercises the public-docs path end to end (placeholder config, no credentials).
        tables = ChurnkeySource().get_documented_tables()
        assert [t["name"] for t in tables] == ["Sessions"]
        assert tables[0]["primary_keys"] == ["_id"]
        assert "Full refresh" in tables[0]["sync_methods"]


class TestChurnkeyValidateCredentials:
    @pytest.mark.parametrize(
        ("validate_return", "expected_ok"),
        [
            ((True, 200), True),
            ((False, 401), False),
            ((False, 403), False),
            ((False, 404), False),
            ((False, None), False),
        ],
    )
    def test_validate_credentials(self, validate_return: tuple[bool, int | None], expected_ok: bool) -> None:
        with patch(_VALIDATE, return_value=validate_return):
            ok, error = ChurnkeySource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        if not expected_ok:
            assert error

    def test_app_id_error_is_specific(self) -> None:
        with patch(_VALIDATE, return_value=(False, 404)):
            _, error = ChurnkeySource().validate_credentials(_config(), team_id=1)
        assert error is not None and "App ID" in error


class TestChurnkeyNonRetryableErrors:
    def test_auth_errors_present(self) -> None:
        errors = ChurnkeySource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert any("404" in key for key in errors)


class TestChurnkeyPipeline:
    def test_get_resumable_source_manager(self) -> None:
        manager = ChurnkeySource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChurnkeyResumeConfig

    def test_source_for_pipeline_plumbing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = ChurnkeySource().source_for_pipeline(_config(), manager, _inputs())
        assert response.name == "Sessions"
        assert response.primary_keys == ["_id"]
        assert response.partition_keys == ["createdAt"]
