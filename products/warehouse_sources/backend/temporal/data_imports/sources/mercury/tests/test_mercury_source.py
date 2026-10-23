from typing import Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercury import (
    MercurySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source import MercurySource


def _make_inputs(
    schema_name: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="createdAt" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestMercurySource:
    def setup_method(self) -> None:
        self.source = MercurySource()
        self.config = MercurySourceConfig(api_key="test-token")

    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_valid"),
        [
            (200, None, True),
            (200, "Transactions", True),
            (401, None, False),
            (401, "Transactions", False),
            # A custom-scoped token can be valid without /accounts access, so 403 passes
            # at source-create but fails the per-schema check.
            (403, None, True),
            (403, "Transactions", False),
            (500, None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status: int, schema_name: Optional[str], expected_valid: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if not expected_valid:
            assert error
        assert {request.path for request in network.requests_log} == {"/api/v1/accounts"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer test-token"}
        assert network.session_options[0]["redact_values"] == ("test-token",)


class TestMercurySourceForPipeline:
    def setup_method(self) -> None:
        self.source = MercurySource()
        self.config = MercurySourceConfig(api_key="test-token")
        self.manager = MagicMock(spec=ResumableSourceManager)

    def _run(self, inputs: SourceInputs) -> tuple[MagicMock, SourceResponse]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source.mercury_source"
        ) as mock_source:
            mock_source.return_value.name = inputs.schema_name
            mock_source.return_value.column_hints = None
            response = self.source.source_for_pipeline(self.config, self.manager, inputs)
        return cast(MagicMock, mock_source), response

    def test_plumbs_arguments_to_transport(self) -> None:
        inputs = _make_inputs(
            "Transactions", should_use_incremental_field=True, db_incremental_field_last_value="2026-01-01"
        )
        mock_source, _ = self._run(inputs)

        mock_source.assert_called_once_with(
            api_key="test-token",
            endpoint="Transactions",
            team_id=1,
            job_id="job-id",
            resumable_source_manager=self.manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01",
        )

    @pytest.mark.parametrize(
        ("endpoint", "expected_partition_key"),
        [
            ("Transactions", "createdAt"),
            ("Events", "occurredAt"),
            ("Recipients", None),
            ("Users", None),
        ],
    )
    def test_partitioning_uses_stable_datetime_fields(
        self, endpoint: str, expected_partition_key: Optional[str]
    ) -> None:
        result = SourceDriver(self.source, self.config).run(
            endpoint,
            [ScriptedResponse(json={endpoint.lower(): [], "page": {"nextPage": None}})],
        )
        assert result.raised is None
        response = result.response
        assert response is not None

        if expected_partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition_key]
            assert response.partition_mode == "datetime"
