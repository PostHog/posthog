from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import (
    MAX_DATASET_IDS,
    SOCRATA_UPDATED_AT_FIELD,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.source import CdcOpenDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cdcopendata import (
    CdcOpenDataSourceConfig,
)


class TestCdcOpenDataSource:
    def setup_method(self) -> None:
        self.source = CdcOpenDataSource()
        self.config = CdcOpenDataSourceConfig(dataset_ids="9bhg-hcku, vbim-akqf\nhk9y-quqm", app_token=None)

    def test_ships_released_on_alpha(self) -> None:
        # A finished source must not carry `unreleasedSource=True` (that hides it entirely);
        # ALPHA is the correct soft label for a new, lightly-tested but visible source.
        config = self.source.get_source_config
        assert config.unreleasedSource is not True
        assert config.releaseStatus is not None
        assert config.releaseStatus.value == "alpha"

    def test_does_not_advertise_a_static_table_catalog(self) -> None:
        # The table set is whatever dataset IDs the user configures, not a vendor-fixed
        # catalog, so this must stay False (the base default) or public docs would try to
        # render a table list from an empty placeholder config.
        assert self.source.lists_tables_without_credentials is False

    def test_get_schemas_returns_one_schema_per_dataset_id(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == ["9bhg-hcku", "vbim-akqf", "hk9y-quqm"]
        for schema in schemas:
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert schema.detected_primary_keys == [":id"]
            assert [f["field"] for f in schema.incremental_fields] == [SOCRATA_UPDATED_AT_FIELD]

    def test_get_schemas_dedupes_and_trims_whitespace(self) -> None:
        config = CdcOpenDataSourceConfig(dataset_ids=" 9bhg-hcku ,9bhg-hcku\n vbim-akqf", app_token=None)
        schemas = self.source.get_schemas(config, team_id=1)
        assert [s.name for s in schemas] == ["9bhg-hcku", "vbim-akqf"]

    def test_get_schemas_empty_when_no_dataset_ids_configured(self) -> None:
        config = CdcOpenDataSourceConfig(dataset_ids="", app_token=None)
        assert self.source.get_schemas(config, team_id=1) == []

    def test_get_schemas_names_filter_narrows_result(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["vbim-akqf"])
        assert [s.name for s in schemas] == ["vbim-akqf"]

    @parameterized.expand(
        [
            ("forbidden", "403 Client Error: Forbidden for url: https://data.cdc.gov/resource/x.json?%24limit=1"),
            ("not_found", "404 Client Error: Not Found for url: https://data.cdc.gov/resource/x.json?%24limit=1"),
        ]
    )
    def test_non_retryable_errors_cover_bad_token_and_missing_dataset(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_requires_at_least_one_dataset_id(self) -> None:
        config = CdcOpenDataSourceConfig(dataset_ids="   ", app_token=None)
        with mock.patch.object(source_module, "validate_cdc_open_data_credentials") as mock_validate:
            valid, message = self.source.validate_credentials(config, team_id=1)
        assert valid is False
        assert message == "Enter at least one CDC dataset ID to sync."
        mock_validate.assert_not_called()

    def test_validate_credentials_rejects_malformed_dataset_id_without_probing(self) -> None:
        config = CdcOpenDataSourceConfig(dataset_ids="not-a-valid-id-at-all", app_token=None)
        with mock.patch.object(source_module, "validate_cdc_open_data_credentials") as mock_validate:
            valid, message = self.source.validate_credentials(config, team_id=1)
        assert valid is False
        assert message is not None and "not-a-valid-id-at-all" in message
        mock_validate.assert_not_called()

    def test_validate_credentials_rejects_too_many_dataset_ids_without_probing(self) -> None:
        too_many_ids = ",".join(f"{i:04d}-{i:04d}" for i in range(MAX_DATASET_IDS + 1))
        config = CdcOpenDataSourceConfig(dataset_ids=too_many_ids, app_token=None)
        with mock.patch.object(source_module, "validate_cdc_open_data_credentials") as mock_validate:
            valid, message = self.source.validate_credentials(config, team_id=1)
        assert valid is False
        assert message is not None and str(MAX_DATASET_IDS) in message
        mock_validate.assert_not_called()

    def test_validate_credentials_probes_first_dataset_at_source_create(self) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            valid, message = self.source.validate_credentials(self.config, team_id=1, schema_name=None)
        assert (valid, message) == (True, None)
        mock_validate.assert_called_once_with("", "9bhg-hcku")

    def test_validate_credentials_probes_the_requested_schema(self) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            self.source.validate_credentials(self.config, team_id=1, schema_name="vbim-akqf")
        mock_validate.assert_called_once_with("", "vbim-akqf")

    def test_validate_credentials_falls_back_to_first_dataset_for_unknown_schema_name(self) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            self.source.validate_credentials(self.config, team_id=1, schema_name="not-configured")
        mock_validate.assert_called_once_with("", "9bhg-hcku")

    @parameterized.expand(
        [
            ("incremental_sync_passes_last_value", True, "2024-01-01", "2024-01-01"),
            ("full_refresh_omits_last_value", False, "2024-01-01", None),
        ]
    )
    def test_source_for_pipeline_passes_expected_kwargs(
        self, _name: str, should_use_incremental_field: bool, last_value: str, expected_last_value: str | None
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "9bhg-hcku"
        inputs.team_id = 1
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = last_value
        manager = mock.MagicMock()

        with mock.patch.object(source_module, "cdc_open_data_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        _, kwargs = mock_source.call_args
        assert kwargs["dataset_id"] == "9bhg-hcku"
        assert kwargs["app_token"] == ""  # `config.app_token` is None; the source coerces it to ""
        assert kwargs["team_id"] == 1
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] == should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
