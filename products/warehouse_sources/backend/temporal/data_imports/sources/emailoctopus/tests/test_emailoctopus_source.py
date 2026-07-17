from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EmailOctopusResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.source import EmailOctopusSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> Any:
    config = MagicMock()
    config.api_key = "eo_key"
    return config


class TestEmailOctopusSourceConfig:
    def test_source_type(self) -> None:
        assert EmailOctopusSource().source_type == ExternalDataSourceType.EMAILOCTOPUS

    def test_source_config_basics(self) -> None:
        config = EmailOctopusSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.EMAIL_OCTOPUS
        assert config.label == "EmailOctopus"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible: no unreleasedSource flag.
        assert not config.unreleasedSource

    def test_api_key_field_is_a_required_secret(self) -> None:
        fields = EmailOctopusSource().get_source_config.fields
        api_key_fields = [f for f in fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key"]
        assert len(api_key_fields) == 1
        api_key = api_key_fields[0]
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True


class TestEmailOctopusGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        names = {s.name for s in EmailOctopusSource().get_schemas(_config(), team_id=1)}
        assert names == {"lists", "campaigns", "contacts"}

    @parameterized.expand(
        [
            ("lists", False),
            ("campaigns", False),
            ("contacts", True),
        ]
    )
    def test_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in EmailOctopusSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports_incremental

    def test_contacts_incremental_fields(self) -> None:
        schemas = {s.name: s for s in EmailOctopusSource().get_schemas(_config(), team_id=1)}
        fields = {f["field"] for f in schemas["contacts"].incremental_fields}
        assert fields == {"created_at", "last_updated_at"}

    def test_names_filter(self) -> None:
        schemas = EmailOctopusSource().get_schemas(_config(), team_id=1, names=["contacts"])
        assert [s.name for s in schemas] == ["contacts"]


class TestEmailOctopusValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate(self, _name: str, is_valid: bool) -> None:
        with patch.object(source_module, "validate_emailoctopus_credentials", return_value=is_valid):
            ok, message = EmailOctopusSource().validate_credentials(_config(), team_id=1)
        assert ok is is_valid
        assert (message is None) is is_valid


class TestEmailOctopusNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.emailoctopus.com/lists?limit=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.emailoctopus.com/campaigns"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = EmailOctopusSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.emailoctopus.com/lists"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.emailoctopus.com/lists"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = EmailOctopusSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestEmailOctopusResumableAndPipeline:
    def _inputs(self, schema_name: str) -> SourceInputs:
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

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = EmailOctopusSource().get_resumable_source_manager(self._inputs("contacts"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EmailOctopusResumeConfig

    def test_source_for_pipeline_plumbs_endpoint(self) -> None:
        inputs = self._inputs("contacts")
        manager = EmailOctopusSource().get_resumable_source_manager(inputs)
        response = EmailOctopusSource().source_for_pipeline(_config(), manager, inputs)
        assert response.name == "contacts"
        assert response.primary_keys == ["list_id", "id"]


class TestEmailOctopusCanonicalDescriptions:
    def test_documents_every_endpoint(self) -> None:
        descriptions = EmailOctopusSource().get_canonical_descriptions()
        assert set(descriptions.keys()) == {"lists", "campaigns", "contacts"}
        assert "list_id" in descriptions["contacts"]["columns"]
