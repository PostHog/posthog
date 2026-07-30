from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VeracodeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.source import VeracodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.veracode import VeracodeResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> VeracodeSourceConfig:
    return VeracodeSourceConfig(api_id="the-id", api_secret="the-secret", region="com")


def _inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestVeracodeSourceConfig:
    def test_source_type(self) -> None:
        assert VeracodeSource().source_type == ExternalDataSourceType.VERACODE

    def test_config_is_visible_and_alpha(self) -> None:
        config = VeracodeSource().get_source_config
        # A finished source must never keep unreleasedSource (that hides it from every user).
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_config_fields(self) -> None:
        config = VeracodeSource().get_source_config
        assert [f.name for f in config.fields] == ["api_id", "api_secret", "region"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public docs table list to render.
        assert VeracodeSource().lists_tables_without_credentials is True
        assert len(VeracodeSource().get_documented_tables()) == 4


class TestGetSchemas:
    def test_only_applications_supports_incremental(self) -> None:
        schemas = {s.name: s for s in VeracodeSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"applications", "sandboxes", "findings", "sca_findings"}
        assert schemas["applications"].supports_incremental is True
        assert [f["field"] for f in schemas["applications"].incremental_fields] == ["modified"]
        for full_refresh in ("sandboxes", "findings", "sca_findings"):
            assert schemas[full_refresh].supports_incremental is False

    def test_names_filter(self) -> None:
        schemas = VeracodeSource().get_schemas(_config(), team_id=1, names=["findings"])
        assert [s.name for s in schemas] == ["findings"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), None, True),
            ("forbidden_at_create_is_accepted", (False, 403), None, True),
            ("forbidden_for_schema_is_rejected", (False, 403), "findings", False),
            ("unauthorized_is_rejected", (False, 401), None, False),
            ("unreachable_is_rejected", (False, None), None, False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, Optional[int]], schema_name: Optional[str], expected_ok: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.veracode.source.validate_veracode_credentials",
            return_value=probe_result,
        ):
            ok, error = VeracodeSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestResumableWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = VeracodeSource().get_resumable_source_manager(_inputs("applications"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is VeracodeResumeConfig

    def test_source_for_pipeline_returns_named_response(self) -> None:
        manager = MagicMock()
        response = VeracodeSource().source_for_pipeline(_config(), manager, _inputs("findings"))
        assert response.name == "findings"
        assert response.primary_keys == ["application_guid", "issue_id"]

    def test_source_for_pipeline_rejects_unknown_endpoint(self) -> None:
        try:
            VeracodeSource().source_for_pipeline(_config(), MagicMock(), _inputs("not_an_endpoint"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for unknown endpoint")


class TestNonRetryableErrors:
    def test_auth_errors_are_non_retryable(self) -> None:
        errors = VeracodeSource().get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors
