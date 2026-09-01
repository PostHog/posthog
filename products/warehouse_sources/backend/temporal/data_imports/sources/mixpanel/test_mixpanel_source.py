from typing import Optional

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixpanel import (
    MixpanelSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.source import MixpanelSource

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


class TestApiVersions:
    def test_new_sources_default_to_2_0(self) -> None:
        # New sources are stamped with `default_version`; existing pins are unaffected.
        assert MixpanelSource().default_version == "2.0"
        assert set(MixpanelSource().supported_versions) == {"v1", "2.0"}

    @parameterized.expand(
        [
            ("no_pin_uses_default", None, "2.0"),
            ("v1_pin_honored", "v1", "v1"),
            ("2_0_pin_honored", "2.0", "2.0"),
        ]
    )
    def test_source_for_pipeline_threads_resolved_version(self, _name: str, pin: Optional[str], expected: str) -> None:
        with patch.object(source_module, "mixpanel_source") as mock_source:
            MixpanelSource().source_for_pipeline(_config(), MagicMock(), _inputs(api_version=pin))
        assert mock_source.call_args.kwargs["api_version"] == expected


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


class TestNonRetryableErrors:
    source = MixpanelSource()

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://mixpanel.com/api/query/cohorts/list"),
            ("403", "403 Client Error: Forbidden for url: https://mixpanel.com/api/query/engage"),
            ("402", "402 Client Error: Payment Required for url: https://mixpanel.com/api/query/cohorts/list"),
        ]
    )
    def test_billing_and_auth_failures_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("429", "429 Client Error: Too Many Requests for url: https://mixpanel.com/api/query/engage"),
            ("500", "500 Server Error: Internal Server Error for url: https://mixpanel.com/api/query/engage"),
        ]
    )
    def test_transient_failures_stay_retryable(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())
