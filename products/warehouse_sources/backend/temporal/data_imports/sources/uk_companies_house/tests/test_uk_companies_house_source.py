from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukcompanieshouse import (
    UkCompaniesHouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    COMPANIES,
    ENDPOINT_SPECS,
    ENDPOINTS,
    OFFICERS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.source import (
    NO_COMPANY_NUMBERS_ERROR,
    UkCompaniesHouseSource,
)

VALIDATE_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.source.validate_companies_house_credentials"
TRANSPORT_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.source.uk_companies_house_source"


def _make_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestUkCompaniesHouseSource:
    def setup_method(self) -> None:
        self.source = UkCompaniesHouseSource()
        self.config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers="6400\nSC123456")

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_keys_are_unique_table_wide(self, endpoint: str) -> None:
        # Every child table aggregates rows from every configured company, so the company the row
        # was fetched for has to be part of the key.
        spec = ENDPOINT_SPECS[endpoint]
        if spec.parent_field is None:
            assert spec.primary_key == ["company_number"]
        else:
            assert spec.parent_field in spec.primary_key

    @parameterized.expand(
        [
            ("blank", "", NO_COMPANY_NUMBERS_ERROR),
            ("separators_only", " , \n ", NO_COMPANY_NUMBERS_ERROR),
            ("malformed_number", "not-a-number", "not valid Companies House company numbers: NOT-A-NUMBER"),
        ]
    )
    def test_validate_credentials_rejects_bad_company_numbers_without_calling_the_api(
        self, _label: str, company_numbers: str, expected_fragment: str
    ) -> None:
        config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers=company_numbers)

        with patch(VALIDATE_TARGET) as mock_validate:
            ok, error = self.source.validate_credentials(config, team_id=123)

        assert ok is False
        assert error is not None and expected_fragment in error
        mock_validate.assert_not_called()

    def test_validate_credentials_probes_the_first_normalized_company_number(self) -> None:
        with patch(VALIDATE_TARGET, return_value=(True, None)) as mock_validate:
            ok, error = self.source.validate_credentials(self.config, team_id=123)

        assert (ok, error) == (True, None)
        mock_validate.assert_called_once_with("test-key", "00006400")

    def test_source_for_pipeline_passes_parsed_company_numbers(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(OFFICERS)

        with patch(TRANSPORT_TARGET, return_value=iter([[{"name": "A"}]])) as mock_transport:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            rows = list(cast("Iterable[Any]", response.items()))

        assert rows == [[{"name": "A"}]]
        assert mock_transport.call_args.kwargs["company_numbers"] == ["00006400", "SC123456"]
        assert mock_transport.call_args.kwargs["endpoint"] == OFFICERS

    def test_source_for_pipeline_rejects_an_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown Companies House endpoint"):
            self.source.source_for_pipeline(
                self.config, MagicMock(spec=ResumableSourceManager), _make_inputs("NotATable")
            )

    def test_source_for_pipeline_rejects_an_empty_company_list(self) -> None:
        config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers="")

        with pytest.raises(ValueError, match=NO_COMPANY_NUMBERS_ERROR):
            self.source.source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), _make_inputs(COMPANIES))
