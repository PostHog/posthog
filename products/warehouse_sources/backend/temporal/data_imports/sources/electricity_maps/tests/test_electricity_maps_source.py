from typing import Any

import pytest
from unittest import mock
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source import (
    ElectricityMapsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source"
    ".validate_electricity_maps_credentials"
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "carbon_intensity",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestElectricityMapsCredentialValidation:
    @pytest.mark.parametrize("zones", ["", " , ,"])
    def test_rejects_empty_zone_list_without_calling_the_api(self, zones: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "zone" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        ("zones", "malformed"),
        [
            ("DE, https://example.com", "HTTPS://EXAMPLE.COM"),
            ("DE DE", "DE DE"),
        ],
    )
    def test_rejects_malformed_zones_without_calling_the_api(self, zones: str, malformed: str) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones=zones)
        with patch(_VALIDATE) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and malformed in message
        mock_validate.assert_not_called()

    def test_delegates_normalized_zones_to_the_api_probe(self) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="de, dk-dk1")
        with patch(_VALIDATE, return_value=(True, None)) as mock_validate:
            is_valid, message = ElectricityMapsSource().validate_credentials(config, team_id=1)

        assert (is_valid, message) == (True, None)
        mock_validate.assert_called_once_with("token", ["DE", "DK-DK1"])


class TestElectricityMapsVersionDispatch:
    def test_default_version_is_v4(self) -> None:
        # New sources are created on the newest wire; a NULL pin resolves to it too.
        source = ElectricityMapsSource()
        assert source.default_version == "v4"
        assert source.supported_versions == ("v3", "v4")
        assert source.resolve_api_version(None) == "v4"

    @pytest.mark.parametrize(
        ("pin", "expected_version"),
        [
            (None, "v4"),
            ("v3", "v3"),
            ("v4", "v4"),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source"
        ".electricity_maps_source"
    )
    def test_source_for_pipeline_plumbs_resolved_version(
        self, mock_source: mock.MagicMock, pin: str | None, expected_version: str
    ) -> None:
        config = ElectricityMapsSourceConfig(api_token="token", zones="de, dk-dk1", history_days=14)
        inputs = _make_inputs(schema_name="power_breakdown", team_id=99, job_id="job-xyz", api_version=pin)
        manager = mock.MagicMock(spec=ResumableSourceManager)

        ElectricityMapsSource().source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once_with(
            api_token="token",
            zones=["DE", "DK-DK1"],
            endpoint="power_breakdown",
            api_version=expected_version,
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            history_days=14,
        )
