from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal import (
    ECBResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source import EcbDataPortalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ecbdataportal import (
    EcbDataPortalSourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "eur_exchange_rates",
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


class TestEcbDataPortalSource:
    def setup_method(self) -> None:
        self.source = EcbDataPortalSource()
        self.team_id = 123
        self.config = EcbDataPortalSourceConfig()

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "ECB Data Portal is unreachable (status 503). Try again later."),
        ],
    )
    def test_validate_credentials(self, mock_return: tuple[bool, str | None]) -> None:
        status_code = 200 if mock_return[0] else 503

        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert self.source.validate_credentials(self.config, self.team_id) == mock_return

        assert {request.path for request in network.requests_log} == {"/service/data/EXR/D.USD.EUR.SP00.A"}

    def test_get_non_retryable_errors_covers_waf_block(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "Your access has been blocked due to security concerns" in errors
        assert all(message for message in errors.values())

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ECBResumeConfig

    def test_source_for_pipeline_plumbs_arguments_when_incremental(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "key_interest_rates",
            [ScriptedResponse(body=b"KEY,TIME_PERIOD,OBS_VALUE\nFM.B.U2.EUR.4F.KR.DFR.LEV,2024-01-01,4.5")],
            incremental_field="TIME_PERIOD",
            db_incremental_field_last_value="2024-01-01",
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "key_interest_rates"
        assert result.paths == ["/service/data/FM/B.U2.EUR.4F.KR..LEV"]
        assert result.params("startPeriod") == ["2024-01-01"]
        assert result.rows == [{"KEY": "FM.B.U2.EUR.4F.KR.DFR.LEV", "TIME_PERIOD": "2024-01-01", "OBS_VALUE": "4.5"}]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source.ecb_data_portal_source"
    )
    def test_source_for_pipeline_ignores_stale_last_value_when_not_incremental(
        self, mock_source: mock.MagicMock
    ) -> None:
        # A previously-stored last_value must not leak into a full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2024-01-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
