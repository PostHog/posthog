from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal import (
    ECBResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source import EcbDataPortalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ecbdataportal import (
    EcbDataPortalSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ECBDATAPORTAL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "EcbDataPortal"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category is not None
        assert config.iconPath == "/static/services/ecb_data_portal.png"
        # Fully open, keyless API — the connect form has no credential fields.
        assert config.fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_all_support_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # TIME_PERIOD is server-side filterable (startPeriod/endPeriod) on every flow.
        assert all(s.supports_incremental for s in schemas)
        assert all(len(s.incremental_fields) == 1 for s in schemas)
        assert all(s.incremental_fields[0]["field"] == "TIME_PERIOD" for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["hicp_inflation"])
        assert [s.name for s in schemas] == ["hicp_inflation"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "ECB Data Portal is unreachable (status 503). Try again later."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source.check_connection"
    )
    def test_validate_credentials(self, mock_check: mock.MagicMock, mock_return: tuple[bool, str | None]) -> None:
        mock_check.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_check.assert_called_once_with()

    def test_get_non_retryable_errors_covers_waf_block(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "Your access has been blocked due to security concerns" in errors
        assert all(message for message in errors.values())

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ECBResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.source.ecb_data_portal_source"
    )
    def test_source_for_pipeline_plumbs_arguments_when_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="key_interest_rates",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            endpoint="key_interest_rates",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01",
        )

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
