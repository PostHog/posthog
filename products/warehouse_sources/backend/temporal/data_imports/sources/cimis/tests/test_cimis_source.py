from typing import Any, Literal

from unittest import mock

import requests
from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.cimis import cimis
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.source import CimisSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CimisSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(app_key: str = "key", targets: str | None = "2", unit: Literal["E", "M"] = "E") -> CimisSourceConfig:
    return CimisSourceConfig(app_key=app_key, targets=targets, unit_of_measure=unit)


class TestCimisSourceConfig:
    def test_source_type(self) -> None:
        assert CimisSource().source_type == ExternalDataSourceType.CIMIS

    def test_source_config_metadata(self) -> None:
        config = CimisSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cimis"

    def test_source_config_fields(self) -> None:
        fields = {f.name: f for f in CimisSource().get_source_config.fields}
        assert set(fields) == {"app_key", "targets", "unit_of_measure"}
        app_key = fields["app_key"]
        targets = fields["targets"]
        assert isinstance(app_key, SourceFieldInputConfig)
        assert isinstance(targets, SourceFieldInputConfig)
        # The credential must be flagged secret so the serializer treats it as sensitive.
        assert app_key.required is True
        assert app_key.secret is True
        # Targets is optional so the metadata tables can sync without it.
        assert targets.required is False


class TestCimisGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = CimisSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == {
            "stations",
            "station_zipcodes",
            "spatial_zipcodes",
            "daily_data",
            "hourly_data",
        }

    def test_filters_by_names(self) -> None:
        schemas = CimisSource().get_schemas(_config(), team_id=1, names=["stations"])
        assert [s.name for s in schemas] == ["stations"]

    @parameterized.expand(
        [
            ("daily_data", True),
            ("hourly_data", True),
            ("stations", False),
            ("station_zipcodes", False),
            ("spatial_zipcodes", False),
        ]
    )
    def test_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schema = next(s for s in CimisSource().get_schemas(_config(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["Date"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the docs table catalog should render.
        tables = CimisSource().get_documented_tables()
        assert {t["name"] for t in tables} == {
            "stations",
            "station_zipcodes",
            "spatial_zipcodes",
            "daily_data",
            "hourly_data",
        }


class TestCimisValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("bad", 403, False)])
    def test_validate_credentials(self, _name: str, status: int, expected: bool) -> None:
        response = mock.Mock(spec=requests.Response)
        response.status_code = status
        session = mock.Mock()
        session.get.return_value = response
        with mock.patch.object(cimis, "make_tracked_session", return_value=session):
            ok, _msg = CimisSource().validate_credentials(_config(), team_id=1)
        assert ok is expected


class TestCimisNonRetryableErrors:
    def test_marks_auth_errors_non_retryable(self) -> None:
        errors = CimisSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestCimisSourceForPipeline:
    def test_plumbs_config_and_inputs_into_source_response(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "daily_data"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2023-01-01"
        inputs.logger = mock.Mock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with mock.patch.object(cimis, "cimis_source"):
            from products.warehouse_sources.backend.temporal.data_imports.sources.cimis import source as source_mod

            with mock.patch.object(source_mod, "cimis_source", side_effect=fake_source):
                source_mod.CimisSource().source_for_pipeline(_config(targets="2,8"), inputs)

        assert captured["endpoint"] == "daily_data"
        assert captured["app_key"] == "key"
        assert captured["targets"] == ["2", "8"]
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2023-01-01"

    def test_incremental_value_dropped_when_not_incremental(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "stations"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2023-01-01"
        inputs.logger = mock.Mock()

        captured: dict[str, Any] = {}
        from products.warehouse_sources.backend.temporal.data_imports.sources.cimis import source as source_mod

        with mock.patch.object(source_mod, "cimis_source", side_effect=lambda **kw: captured.update(kw)):
            source_mod.CimisSource().source_for_pipeline(_config(), inputs)

        assert captured["db_incremental_field_last_value"] is None
