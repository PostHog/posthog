from typing import Any, Literal

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cimis import cimis
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.source import CimisSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cimis import CimisSourceConfig


def _config(app_key: str = "key", targets: str | None = "2", unit: Literal["E", "M"] = "E") -> CimisSourceConfig:
    return CimisSourceConfig(app_key=app_key, targets=targets, unit_of_measure=unit)


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
