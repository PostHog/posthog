from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import (
    MAX_DATASET_IDS,
    SODA2_API_VERSION,
    SODA3_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.source import CdcOpenDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cdcopendata import (
    CdcOpenDataSourceConfig,
)


class TestCdcOpenDataSource:
    def setup_method(self) -> None:
        self.source = CdcOpenDataSource()
        self.config = CdcOpenDataSourceConfig(dataset_ids="9bhg-hcku, vbim-akqf\nhk9y-quqm", app_token=None)

    def test_does_not_advertise_a_static_table_catalog(self) -> None:
        # The table set is whatever dataset IDs the user configures, not a vendor-fixed
        # catalog, so this must stay False (the base default) or public docs would try to
        # render a table list from an empty placeholder config.
        assert self.source.lists_tables_without_credentials is False

    def test_get_schemas_dedupes_and_trims_whitespace(self) -> None:
        config = CdcOpenDataSourceConfig(dataset_ids=" 9bhg-hcku ,9bhg-hcku\n vbim-akqf", app_token=None)
        schemas = self.source.get_schemas(config, team_id=1)
        assert [s.name for s in schemas] == ["9bhg-hcku", "vbim-akqf"]

    def test_get_schemas_names_filter_narrows_result(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["vbim-akqf"])
        assert [s.name for s in schemas] == ["vbim-akqf"]

    @parameterized.expand(
        [
            (
                "soda2_forbidden",
                "403 Client Error: Forbidden for url: https://data.cdc.gov/resource/x.json?%24limit=1",
                "remove it",
            ),
            (
                "soda2_not_found",
                "404 Client Error: Not Found for url: https://data.cdc.gov/resource/x.json?%24limit=1",
                None,
            ),
            (
                "soda3_forbidden",
                "403 Client Error: Forbidden for url: https://data.cdc.gov/api/v3/views/x/query.json",
                "Invalid or missing",
            ),
            (
                "soda3_not_found",
                "404 Client Error: Not Found for url: https://data.cdc.gov/api/v3/views/x/query.json",
                None,
            ),
        ]
    )
    def test_non_retryable_errors_cover_bad_token_and_missing_dataset(
        self, _name: str, observed: str, expected_in_message: str | None
    ) -> None:
        # The first matching pattern wins when the error is surfaced, so check that one.
        message = next(
            (msg for key, msg in self.source.get_non_retryable_errors().items() if key in observed), "<no match>"
        )
        assert message != "<no match>"
        if expected_in_message is not None:
            assert message is not None and expected_in_message in message

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

    @parameterized.expand(
        [
            ("new_source_uses_default", None, SODA3_API_VERSION),
            ("pinned_legacy_source", SODA2_API_VERSION, SODA2_API_VERSION),
            ("pinned_soda3_source", SODA3_API_VERSION, SODA3_API_VERSION),
        ]
    )
    def test_validate_credentials_probes_first_dataset_at_source_create(
        self, _name: str, api_version: str | None, expected_version: str
    ) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            valid, message = self.source.validate_credentials(
                self.config, team_id=1, schema_name=None, api_version=api_version
            )
        assert (valid, message) == (True, None)
        mock_validate.assert_called_once_with("", "9bhg-hcku", expected_version)

    def test_validate_credentials_probes_the_requested_schema(self) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            self.source.validate_credentials(self.config, team_id=1, schema_name="vbim-akqf")
        mock_validate.assert_called_once_with("", "vbim-akqf", SODA3_API_VERSION)

    def test_validate_credentials_falls_back_to_first_dataset_for_unknown_schema_name(self) -> None:
        with mock.patch.object(
            source_module, "validate_cdc_open_data_credentials", return_value=(True, None)
        ) as mock_validate:
            self.source.validate_credentials(self.config, team_id=1, schema_name="not-configured")
        mock_validate.assert_called_once_with("", "9bhg-hcku", SODA3_API_VERSION)

    @parameterized.expand(
        [
            ("incremental_sync_passes_last_value", True, "2024-01-01", "2024-01-01", SODA2_API_VERSION),
            ("full_refresh_omits_last_value", False, "2024-01-01", None, SODA2_API_VERSION),
            ("soda3_pin_reaches_request_layer", True, "2024-01-01", "2024-01-01", SODA3_API_VERSION),
        ]
    )
    def test_source_for_pipeline_passes_expected_kwargs(
        self,
        _name: str,
        should_use_incremental_field: bool,
        last_value: str,
        expected_last_value: str | None,
        api_version: str,
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "9bhg-hcku"
        inputs.team_id = 1
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = last_value
        inputs.api_version = api_version
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
        assert kwargs["api_version"] == api_version
