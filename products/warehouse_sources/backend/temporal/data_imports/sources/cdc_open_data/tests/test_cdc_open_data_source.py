from unittest import mock

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

    def test_get_schemas_returns_one_schema_per_dataset_id(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == ["9bhg-hcku", "vbim-akqf", "hk9y-quqm"]
        for schema in schemas:
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert schema.detected_primary_keys == [":id"]
            assert [f["field"] for f in schema.incremental_fields] == [SOCRATA_UPDATED_AT_FIELD]

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
