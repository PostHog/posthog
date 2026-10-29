from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kongkonnect import (
    KongKonnectSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.source import (
    KongKonnectSource,
    _coerce_lookback_days,
)


def _config(**overrides: Any) -> KongKonnectSourceConfig:
    data = {"api_token": "kpat_test", "region": "us"}
    data.update(overrides)
    return KongKonnectSourceConfig.from_dict(data)


class TestSourceConfig:
    def test_connection_host_fields_includes_region(self) -> None:
        # `region` selects the host the stored access token is sent to, so editing it must re-require the secret.
        assert KongKonnectSource().connection_host_fields == ["region"]


class TestGetSchemas:
    def test_only_time_windowed_endpoints_support_incremental(self) -> None:
        schemas = {s.name: s for s in KongKonnectSource().get_schemas(_config(), team_id=1)}
        assert schemas["api_requests"].supports_incremental is True
        assert [f["field"] for f in schemas["api_requests"].incremental_fields] == ["request_start"]
        assert schemas["daily_service_metrics"].supports_incremental is True
        assert [f["field"] for f in schemas["daily_service_metrics"].incremental_fields] == ["day"]
        # The lookup list endpoints have no server-side timestamp filter, so they must stay full refresh.
        for name in set(schemas) - {"api_requests", "daily_service_metrics"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False


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
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_plumbs_region_and_lookback(self) -> None:
        driver = SourceDriver(KongKonnectSource(), _config(region="eu", lookback_days="5"))
        result = driver.run(
            "api_requests",
            [ScriptedResponse(json={"results": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.requests[0].origin == "https://eu.api.konghq.com"
        assert result.requests[0].json()["time_range"]["start"] == "2026-01-01T00:00:00Z"
        full_refresh = driver.run("api_requests", [ScriptedResponse(json={"results": []})])
        assert full_refresh.raised is None
        assert full_refresh.requests[0].json()["time_range"]["start"] == "2026-06-10T12:00:00Z"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_incremental_value_gated_off_when_not_incremental(self) -> None:
        driver = SourceDriver(KongKonnectSource(), _config())
        result = driver.run(
            "api_requests",
            [ScriptedResponse(json={"results": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.requests[0].json()["time_range"]["start"] == "2026-05-16T12:00:00Z"


if __name__ == "__main__":
    pytest.main([__file__])
