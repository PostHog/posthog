from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualtrics import (
    QualtricsAuthMethodConfig,
    QualtricsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.qualtrics import (
    QualtricsCredentials,
    QualtricsResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

EXPECTED_ENDPOINTS = {
    "surveys",
    "users",
    "groups",
    "divisions",
    "distributions",
    "survey_questions",
    "survey_responses",
}


def _config(selection: str = "api_token") -> QualtricsSourceConfig:
    return QualtricsSourceConfig(
        datacenter_id="iad1",
        auth_method=QualtricsAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            api_token="tok-123",
            client_id="client",
            client_secret="shhh",
        ),
    )


def _inputs(schema_name: str = "surveys", **kwargs: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(kwargs)
    return SourceInputs(**defaults)


def _field_names(fields: list[FieldType]) -> list[str]:
    return [field.name for field in fields]


class TestQualtricsSource:
    def setup_method(self) -> None:
        self.source = source_module.QualtricsSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.QUALTRICS

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        # A finished source must be visible; `unreleasedSource` hides it from users entirely.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_collects_a_host_and_both_auth_methods(self) -> None:
        fields = self.source.get_source_config.fields

        assert _field_names(fields) == ["datacenter_id", "auth_method"]
        datacenter, auth = fields
        assert isinstance(datacenter, SourceFieldInputConfig)
        assert datacenter.required is True
        assert isinstance(auth, SourceFieldSelectConfig)
        assert [option.value for option in auth.options] == ["api_token", "oauth_client_credentials"]

    def test_secret_fields_are_marked_secret(self) -> None:
        auth = self.source.get_source_config.fields[1]
        assert isinstance(auth, SourceFieldSelectConfig)
        secrets = {
            field.name: field.secret
            for option in auth.options
            for field in (option.fields or [])
            if isinstance(field, SourceFieldInputConfig)
        }

        assert secrets == {"api_token": True, "client_id": False, "client_secret": True}

    def test_retargeting_the_host_re_requires_credentials(self) -> None:
        assert self.source.connection_host_fields == ["datacenter_id"]

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1)

        assert {schema.name for schema in schemas} == EXPECTED_ENDPOINTS

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["surveys"])

        assert [schema.name for schema in schemas] == ["surveys"]

    def test_only_responses_sync_incrementally(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(_config(), team_id=1)}

        responses = schemas["survey_responses"]
        assert responses.supports_incremental is True
        # Exported responses can be restated under the same id, so append would duplicate them.
        assert responses.supports_append is False
        assert [field["field"] for field in responses.incremental_fields] == ["recordedDate"]
        assert all(not schemas[name].supports_incremental for name in EXPECTED_ENDPOINTS - {"survey_responses"})

    def test_tables_are_listed_for_public_docs(self) -> None:
        # `get_schemas` does no I/O, so the docs endpoint can render the catalog credential-free.
        assert self.source.lists_tables_without_credentials is True
        assert {table["name"] for table in self.source.get_documented_tables()} == EXPECTED_ENDPOINTS

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == EXPECTED_ENDPOINTS

    def test_auth_and_permission_errors_are_non_retryable(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert all(message for message in errors.values())

    def test_api_version_is_pinned_to_the_path_the_code_calls(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.resolve_api_version(None) == "v3"

    @pytest.mark.parametrize(
        "selection, expected",
        [
            ("api_token", QualtricsCredentials(method="api_token", api_token="tok-123")),
            (
                "oauth_client_credentials",
                QualtricsCredentials(method="oauth_client_credentials", client_id="client", client_secret="shhh"),
            ),
        ],
    )
    def test_credentials_are_read_from_the_selected_auth_method(
        self, selection: str, expected: QualtricsCredentials
    ) -> None:
        assert source_module._credentials_from_config(_config(selection)) == expected

    def test_validate_credentials_plumbs_config_through(self) -> None:
        with mock.patch.object(source_module, "validate_qualtrics_credentials", return_value=(True, None)) as validate:
            assert self.source.validate_credentials(_config(), team_id=7, schema_name="users") == (True, None)

        assert validate.call_args.kwargs == {
            "datacenter_id": "iad1",
            "credentials": QualtricsCredentials(method="api_token", api_token="tok-123"),
            "api_version": "v3",
            "schema_name": "users",
            "team_id": 7,
        }

    def test_resumable_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is QualtricsResumeConfig

    def test_source_for_pipeline_passes_the_incremental_watermark(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        inputs = _inputs(
            schema_name="survey_responses",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        with mock.patch.object(source_module, "qualtrics_source") as build:
            self.source.source_for_pipeline(_config(), manager, inputs)

        kwargs = build.call_args.kwargs
        assert kwargs["endpoint"] == "survey_responses"
        assert kwargs["api_version"] == "v3"
        assert kwargs["team_id"] == 1
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        inputs = _inputs(
            schema_name="surveys",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        with mock.patch.object(source_module, "qualtrics_source") as build:
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert build.call_args.kwargs["db_incremental_field_last_value"] is None
