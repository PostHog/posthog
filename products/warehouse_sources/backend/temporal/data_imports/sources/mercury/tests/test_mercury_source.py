from typing import Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercury import (
    MercurySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import (
    ENDPOINTS,
    TRANSACTIONS_LOOKBACK_SECONDS,
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

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_only_transactions_supports_incremental(self, endpoint: str) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=[endpoint])
        schema = schemas[0]

        if endpoint == "Transactions":
            assert schema.supports_incremental is True
            assert [f["field"] for f in schema.incremental_fields] == ["createdAt"]
            assert schema.default_incremental_lookback_seconds == TRANSACTIONS_LOOKBACK_SECONDS
        else:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []
            assert schema.default_incremental_lookback_seconds is None

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
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source.check_credentials",
            return_value=status,
        ):
            valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if not expected_valid:
            assert error

    def test_validate_credentials_handles_network_error(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source.check_credentials",
            side_effect=ConnectionError("connection refused"),
        ):
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is False
        assert "connection refused" in str(error)


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

    def test_drops_incremental_value_when_full_refresh(self) -> None:
        inputs = _make_inputs(
            "Transactions", should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01"
        )
        mock_source, _ = self._run(inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
