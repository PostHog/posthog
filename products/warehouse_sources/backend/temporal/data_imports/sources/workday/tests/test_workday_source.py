from typing import Optional, cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workday import (
    WorkdaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    ENDPOINTS,
    WORKDAY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.source import WorkdaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday import WorkdayResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.workday.source"


def _config() -> WorkdaySourceConfig:
    return WorkdaySourceConfig(
        hostname="wd2-impl-services1.workday.com",
        tenant="acme_pt1",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )


class TestWorkdaySource:
    def setup_method(self) -> None:
        self.source = WorkdaySource()
        self.team_id = 123
        self.config = _config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WORKDAY

    def test_get_source_config_is_released(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Workday"
        assert config.label == "Workday"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/workday.png"

    def test_source_fields(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == [
            "hostname",
            "tenant",
            "client_id",
            "client_secret",
            "refresh_token",
        ]

    @pytest.mark.parametrize(
        "field_name, field_type, secret",
        [
            ("hostname", SourceFieldInputConfigType.TEXT, False),
            ("tenant", SourceFieldInputConfigType.TEXT, False),
            ("client_id", SourceFieldInputConfigType.TEXT, False),
            ("client_secret", SourceFieldInputConfigType.PASSWORD, True),
            ("refresh_token", SourceFieldInputConfigType.PASSWORD, True),
        ],
    )
    def test_field_types_and_secrecy(
        self, field_name: str, field_type: SourceFieldInputConfigType, secret: bool
    ) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == field_name)
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == field_type
        assert field.secret is secret
        assert field.required is True

    def test_hostname_is_a_connection_host_field(self) -> None:
        # Retargeting the hostname must force the client secret / refresh token to be re-entered,
        # otherwise the preserved secrets would be replayed at an attacker-chosen host.
        assert self.source.connection_host_fields == ["hostname"]

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_schemas_are_full_refresh_only(self) -> None:
        # Workday's Updated_From/Updated_Through range filters are SOAP-only, so advertising an
        # incremental cursor here would re-read everything at full cost while claiming otherwise.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["workers"])
        assert [s.name for s in schemas] == ["workers"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "mock_return",
        [(True, None), (False, "Invalid Workday hostname")],
    )
    def test_validate_credentials_passes_through(self, mock_return: tuple[bool, Optional[str]]) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_workday_credentials", return_value=mock_return) as validate:
            assert self.source.validate_credentials(self.config, self.team_id) == mock_return

        kwargs = validate.call_args.kwargs
        assert kwargs["hostname"] == "wd2-impl-services1.workday.com"
        assert kwargs["tenant"] == "acme_pt1"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["schema_name"] is None
        # An unpinned source falls back to the declared default staffing version.
        assert kwargs["staffing_version"] == "v7"

    def test_validate_credentials_honors_pinned_version(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_workday_credentials", return_value=(True, None)) as validate:
            self.source.validate_credentials(self.config, self.team_id, schema_name="jobs", api_version="v6")

        assert validate.call_args.kwargs["staffing_version"] == "v6"
        assert validate.call_args.kwargs["schema_name"] == "jobs"

    def test_get_resumable_source_manager_is_bound_to_the_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(cast(SourceInputs, mock.MagicMock()))
        assert manager._data_class is WorkdayResumeConfig

    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "job_profiles"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.api_version = None
        manager = cast(ResumableSourceManager[WorkdayResumeConfig], mock.MagicMock())

        with mock.patch(f"{SOURCE_MODULE}.workday_source") as source_fn:
            self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        kwargs = source_fn.call_args.kwargs
        assert kwargs["endpoint"] == "job_profiles"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"
        assert kwargs["staffing_version"] == "v7"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["resumable_source_manager"] is manager

    def test_every_endpoint_has_a_primary_key(self) -> None:
        assert all(WORKDAY_ENDPOINTS[name].primary_key for name in ENDPOINTS)
