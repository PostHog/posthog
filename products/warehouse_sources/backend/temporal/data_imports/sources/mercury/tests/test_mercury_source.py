from typing import Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercury import (
    MercurySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.mercury import MercuryResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import (
    ENDPOINTS,
    TRANSACTIONS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.source import MercurySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MERCURY

    def test_source_config_is_released_with_alpha_status(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/mercury"

    def test_source_config_requires_secret_api_key(self) -> None:
        fields = self.source.get_source_config.fields

        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["Accounts", "Transactions"])

        assert {schema.name for schema in schemas} == {"Accounts", "Transactions"}

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

    def test_documented_tables_available_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        transactions = next(table for table in tables if table["name"] == "Transactions")
        assert transactions["description"]

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

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs("Transactions"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MercuryResumeConfig

    @pytest.mark.parametrize(
        ("error_message", "should_match"),
        [
            ("401 Client Error: Unauthorized for url: https://api.mercury.com/api/v1/transactions", True),
            ("403 Client Error: Forbidden for url: https://api.mercury.com/api/v1/accounts", True),
            ("500 Server Error: Internal Server Error for url: https://api.mercury.com/api/v1/accounts", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, error_message: str, should_match: bool) -> None:
        patterns = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in patterns) is should_match


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

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_key"),
        [
            ("Accounts", "id"),
            ("Transactions", "id"),
            ("Users", "userId"),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_primary_key: str) -> None:
        _, response = self._run(_make_inputs(endpoint))

        assert response.primary_keys == [expected_primary_key]

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
        _, response = self._run(_make_inputs(endpoint))

        if expected_partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition_key]
            assert response.partition_mode == "datetime"

    def test_sort_mode_is_ascending(self) -> None:
        _, response = self._run(_make_inputs("Transactions"))

        assert response.sort_mode == "asc"
