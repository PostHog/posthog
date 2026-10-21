from typing import Literal

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.source import CimisSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cimis import CimisSourceConfig


def _config(app_key: str = "key", targets: str | None = "2", unit: Literal["E", "M"] = "E") -> CimisSourceConfig:
    return CimisSourceConfig(app_key=app_key, targets=targets, unit_of_measure=unit)


class TestCimisGetSchemas:
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


class TestCimisValidateCredentials:
    @parameterized.expand([("ok", 200, True)])
    def test_validate_credentials(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, _msg = CimisSource().validate_credentials(_config(), team_id=1)
        assert ok is expected
        assert network.requests_log[0].param("appKey") == "key"
        assert network.requests_log[0].param("targets") == "2"


class TestCimisSourceForPipeline:
    @time_machine.travel("2023-01-02 12:00:00", tick=False)
    def test_plumbs_config_and_inputs_into_source_response(self) -> None:
        result = SourceDriver(CimisSource(), _config(targets="2,8")).run(
            "daily_data",
            [ScriptedResponse(json={"Data": {"Providers": []}})],
            incremental_field="Date",
            db_incremental_field_last_value="2023-01-01",
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "daily_data"
        assert result.paths == ["/api/data"]
        assert result.params("appKey") == ["key"]
        assert result.params("targets") == ["2,8"]
        assert result.params("startDate") == ["2023-01-01"]

    def test_incremental_value_dropped_when_not_incremental(self) -> None:
        result = SourceDriver(CimisSource(), _config()).run(
            "daily_data",
            always(ScriptedResponse(json={"Data": {"Providers": []}})),
            db_incremental_field_last_value="2023-01-01",
        )

        assert result.raised is None
        assert result.params("startDate")[0] == "1982-06-07"
