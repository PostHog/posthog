from types import SimpleNamespace
from typing import cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.meteostat import (
    MeteostatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.meteostat import (
    NO_STATIONS_ERROR,
    MeteostatResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    DAILY_ENDPOINT,
    ENDPOINTS,
    MAX_STATIONS,
    METEOSTAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source import MeteostatSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source"


class TestMeteostatSource:
    def setup_method(self):
        self.source = MeteostatSource()
        self.team_id = 123
        self.config = MeteostatSourceConfig(api_key="key-123", station_ids="10637")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.METEOSTAT

    def test_get_source_config_is_released(self):
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.name.value == "Meteostat"
        assert config.iconPath == "/static/services/meteostat.png"

        fields_by_name = {field.name: field for field in config.fields}
        assert set(fields_by_name) == {"api_key", "station_ids", "units", "start_date"}

        api_key = cast(SourceFieldInputConfig, fields_by_name["api_key"])
        assert api_key.required is True
        assert api_key.secret is True

        station_ids = cast(SourceFieldInputConfig, fields_by_name["station_ids"])
        assert station_ids.required is True

        units = fields_by_name["units"]
        assert isinstance(units, SourceFieldSelectConfig)
        assert units.defaultValue == "metric"

        assert cast(SourceFieldInputConfig, fields_by_name["start_date"]).required is False

    def test_get_schemas_returns_every_endpoint_with_matching_incremental_field(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            expected_field = METEOSTAT_ENDPOINTS[schema.name].date_field
            assert {field["field"] for field in schema.incremental_fields} == {expected_field}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[DAILY_ENDPOINT])
        assert [schema.name for schema in schemas] == [DAILY_ENDPOINT]

    def test_non_retryable_errors_cover_missing_stations_and_auth(self):
        errors = self.source.get_non_retryable_errors()
        assert NO_STATIONS_ERROR in errors
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_validate_credentials_rejects_no_stations(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "station" in message.lower()

    def test_validate_credentials_rejects_too_many_stations(self):
        station_ids = ",".join(str(i) for i in range(MAX_STATIONS + 1))
        config = MeteostatSourceConfig(api_key="key-123", station_ids=station_ids)
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and str(MAX_STATIONS) in message

    def test_validate_credentials_rejects_start_date_before_floor(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637", start_date="0001-01-01")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "start date" in message.lower()

    @mock.patch(f"{MODULE}.validate_station")
    def test_validate_credentials_probes_the_first_configured_station(self, mock_validate):
        mock_validate.return_value = (True, None)
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637, 71508")

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert message is None
        mock_validate.assert_called_once_with("key-123", "10637")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MeteostatResumeConfig

    @mock.patch(f"{MODULE}.meteostat_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_source):
        mock_source.return_value = SimpleNamespace(name=DAILY_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(
            schema_name=DAILY_ENDPOINT,
            team_id=self.team_id,
            job_id="job-1",
            logger=logger,
            should_use_incremental_field=True,
            incremental_field="date",
            db_incremental_field_last_value="2026-07-01",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_source.assert_called_once_with(
            api_key="key-123",
            station_ids="10637",
            units="metric",
            start_date=None,
            endpoint_name=DAILY_ENDPOINT,
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01",
        )
        assert response is mock_source.return_value

    @mock.patch(f"{MODULE}.meteostat_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source):
        mock_source.return_value = SimpleNamespace(name=DAILY_ENDPOINT)
        inputs = SimpleNamespace(
            schema_name=DAILY_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-07-01",
        )

        self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), cast(SourceInputs, inputs)
        )

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_render_without_credentials(self):
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)
        for table in tables:
            assert table["description"]

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_canonical_descriptions_cover_every_endpoint(self, endpoint_name):
        descriptions = self.source.get_canonical_descriptions()
        assert endpoint_name in descriptions
        assert descriptions[endpoint_name]["description"]
        assert "station_id" in descriptions[endpoint_name]["columns"]
