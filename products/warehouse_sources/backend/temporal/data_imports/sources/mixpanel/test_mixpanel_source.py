from typing import Optional

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MixpanelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.mixpanel import MixpanelResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.source import MixpanelSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = structlog.get_logger()


def _config() -> MixpanelSourceConfig:
    return MixpanelSource().parse_config(
        {
            "project_id": "123456",
            "service_account_username": "svc",
            "service_account_secret": "shh",
            "region": "eu",
        }
    )


def _inputs(schema_name: str = "export", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": LOGGER,
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSourceType:
    def test_source_type(self) -> None:
        assert MixpanelSource().source_type == ExternalDataSourceType.MIXPANEL


class TestSourceConfig:
    def test_basic_metadata(self) -> None:
        config = MixpanelSource().get_source_config
        assert config.label == "Mixpanel"
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"

    def test_fields(self) -> None:
        fields = {f.name: f for f in MixpanelSource().get_source_config.fields}
        assert set(fields) == {"region", "project_id", "service_account_username", "service_account_secret"}

        assert isinstance(fields["region"], SourceFieldSelectConfig)
        assert {o.value for o in fields["region"].options} == {"us", "eu", "in"}
        assert fields["region"].defaultValue == "us"

        secret = fields["service_account_secret"]
        assert isinstance(secret, SourceFieldInputConfig)
        assert secret.type == SourceFieldInputConfigType.PASSWORD
        assert secret.secret is True

        # The project id / username are not secret inputs
        assert isinstance(fields["project_id"], SourceFieldInputConfig)
        assert fields["project_id"].type == SourceFieldInputConfigType.TEXT


class TestConnectionHostFields:
    def test_region_and_project_require_secret_re_entry(self) -> None:
        assert set(MixpanelSource().connection_host_fields) == {"region", "project_id"}


class TestGetSchemas:
    def test_all_schemas(self) -> None:
        schemas = {s.name: s for s in MixpanelSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"export", "engage", "cohorts", "annotations"}

    @parameterized.expand(
        [
            ("export", True),
            ("engage", False),
            ("cohorts", False),
            ("annotations", False),
        ]
    )
    def test_incremental_support(self, endpoint: str, supports: bool) -> None:
        schemas = {s.name: s for s in MixpanelSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports
        assert schemas[endpoint].supports_append is supports

    def test_export_has_time_incremental_field(self) -> None:
        schemas = {s.name: s for s in MixpanelSource().get_schemas(_config(), team_id=1)}
        fields = schemas["export"].incremental_fields
        assert [f["field"] for f in fields] == ["time"]

    def test_filter_by_names(self) -> None:
        schemas = MixpanelSource().get_schemas(_config(), team_id=1, names=["engage"])
        assert [s.name for s in schemas] == ["engage"]


class TestValidateCredentials:
    @parameterized.expand([("ok", (True, None)), ("bad", (False, "nope"))])
    def test_delegates_to_transport(self, _name: str, result: tuple[bool, Optional[str]]) -> None:
        with patch.object(source_module, "validate_mixpanel_credentials", return_value=result) as mock_validate:
            assert MixpanelSource().validate_credentials(_config(), team_id=1, schema_name="export") == result
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["project_id"] == "123456"
        assert kwargs["username"] == "svc"
        assert kwargs["secret"] == "shh"
        assert kwargs["schema_name"] == "export"


class TestNonRetryableErrors:
    def test_auth_errors_present(self) -> None:
        errors = MixpanelSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = MixpanelSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MixpanelResumeConfig


class TestSourceForPipeline:
    def test_plumbs_arguments(self) -> None:
        config = _config()
        manager = MagicMock()
        with patch.object(source_module, "mixpanel_source") as mock_source:
            MixpanelSource().source_for_pipeline(config, manager, _inputs(schema_name="engage"))
        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["project_id"] == "123456"
        assert kwargs["username"] == "svc"
        assert kwargs["secret"] == "shh"
        assert kwargs["endpoint"] == "engage"
        assert kwargs["manager"] is manager

    def test_incremental_value_passed_only_when_incremental(self) -> None:
        with patch.object(source_module, "mixpanel_source") as mock_source:
            MixpanelSource().source_for_pipeline(
                _config(),
                MagicMock(),
                _inputs(
                    schema_name="export", should_use_incremental_field=True, db_incremental_field_last_value=1700000000
                ),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == 1700000000

    def test_incremental_value_dropped_when_not_incremental(self) -> None:
        with patch.object(source_module, "mixpanel_source") as mock_source:
            MixpanelSource().source_for_pipeline(
                _config(),
                MagicMock(),
                _inputs(
                    schema_name="export", should_use_incremental_field=False, db_incremental_field_last_value=1700000000
                ),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
