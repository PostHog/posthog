from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KongKonnectSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    KongKonnectResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.source import (
    KongKonnectSource,
    _coerce_lookback_days,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(**overrides: Any) -> KongKonnectSourceConfig:
    data = {"api_token": "kpat_test", "region": "us"}
    data.update(overrides)
    return KongKonnectSourceConfig.from_dict(data)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert KongKonnectSource().source_type == ExternalDataSourceType.KONGKONNECT

    def test_ships_visible_as_alpha(self) -> None:
        config = KongKonnectSource().get_source_config
        # A finished source must be visible (no unreleasedSource) and flagged alpha.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_fields_and_requiredness(self) -> None:
        fields = {f.name: f for f in KongKonnectSource().get_source_config.fields}
        assert set(fields) == {"api_token", "region", "lookback_days"}

        api_token = fields["api_token"]
        assert isinstance(api_token, SourceFieldInputConfig)
        assert api_token.required is True

        region = fields["region"]
        assert isinstance(region, SourceFieldSelectConfig)
        assert region.required is True

        lookback_days = fields["lookback_days"]
        assert isinstance(lookback_days, SourceFieldInputConfig)
        assert lookback_days.required is False


class TestGetSchemas:
    def test_api_requests_supports_incremental(self) -> None:
        schemas = KongKonnectSource().get_schemas(_config(), team_id=1)
        assert [s.name for s in schemas] == ["api_requests"]
        schema = schemas[0]
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["request_start"]

    def test_names_filter(self) -> None:
        assert KongKonnectSource().get_schemas(_config(), team_id=1, names=["nonexistent"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static catalog → public docs render the table list.
        assert KongKonnectSource.lists_tables_without_credentials is True
        tables = KongKonnectSource().get_documented_tables()
        assert [t["name"] for t in tables] == ["api_requests"]


class TestValidateCredentials:
    @patch.object(source_module, "validate_kong_konnect_credentials", return_value=True)
    def test_valid(self, _mock: MagicMock) -> None:
        ok, err = KongKonnectSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert err is None

    @patch.object(source_module, "validate_kong_konnect_credentials", return_value=False)
    def test_invalid(self, _mock: MagicMock) -> None:
        ok, err = KongKonnectSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert err is not None

    def test_unknown_region_rejected_without_network(self) -> None:
        with patch.object(source_module, "validate_kong_konnect_credentials") as mock:
            ok, err = KongKonnectSource().validate_credentials(_config(region="mars"), team_id=1)
        assert ok is False
        assert err is not None
        mock.assert_not_called()


class TestCoerceLookbackDays:
    @parameterized.expand(
        [
            ("none", None, DEFAULT_INITIAL_LOOKBACK_DAYS),
            ("positive", 90, 90),
            ("zero", 0, DEFAULT_INITIAL_LOOKBACK_DAYS),
            ("negative", -3, DEFAULT_INITIAL_LOOKBACK_DAYS),
        ]
    )
    def test_coerce(self, _name: str, value: int | None, expected: int) -> None:
        assert _coerce_lookback_days(value) == expected


class TestSourceForPipeline:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = KongKonnectSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is KongKonnectResumeConfig

    @patch.object(source_module, "kong_konnect_source")
    def test_plumbs_region_and_lookback(self, mock_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "api_requests"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        KongKonnectSource().source_for_pipeline(_config(region="eu", lookback_days="5"), MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["lookback_days"] == 5
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @patch.object(source_module, "kong_konnect_source")
    def test_incremental_value_gated_off_when_not_incremental(self, mock_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "api_requests"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        KongKonnectSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


if __name__ == "__main__":
    pytest.main([__file__])
