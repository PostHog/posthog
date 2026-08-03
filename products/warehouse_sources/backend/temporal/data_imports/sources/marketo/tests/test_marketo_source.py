from typing import Any, Optional

import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketo import (
    MarketoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.marketo import MarketoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import (
    ENDPOINTS,
    MARKETO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source import MarketoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.validate_marketo_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.marketo_source"

INCREMENTAL_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if c.incremental_field)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if not c.incremental_field)


def _make_inputs(schema_name: str = "leads", **overrides: Any) -> mock.MagicMock:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
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
    return mock.MagicMock(**defaults)


class TestMarketoSource:
    def setup_method(self) -> None:
        self.source = MarketoSource()
        self.team_id = 123
        self.config = MarketoSourceConfig(
            munchkin_id="123-ABC-456",
            client_id="client-id",
            client_secret="client-secret",
            start_date="2024-01-01",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.MARKETO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Marketo"
        assert config.label == "Marketo"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/marketo.png"

    @pytest.mark.parametrize(
        "name,required,secret",
        [
            ("munchkin_id", True, False),
            ("client_id", True, False),
            ("client_secret", True, True),
            ("start_date", False, False),
        ],
    )
    def test_source_fields(self, name: str, required: bool, secret: bool) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert len(fields) == 4
        assert fields[name].required is required
        assert bool(fields[name].secret) is secret

    def test_api_docs_url_and_public_table_listing(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")
        # get_schemas iterates a static catalog with no I/O, so the docs can render the tables.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_the_whole_endpoint_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert sorted(schema.name for schema in schemas) == sorted(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["leads", "campaigns"])

        assert sorted(schema.name for schema in schemas) == ["campaigns", "leads"]

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_bulk_endpoints_advertise_their_server_side_filter(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [field["field"] for field in schema.incremental_fields] == [
            MARKETO_ENDPOINTS[endpoint].incremental_field
        ]

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_endpoints_without_a_server_side_filter_are_full_refresh(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "probe_result,expected",
        [
            ((True, None), (True, None)),
            (
                (False, "Invalid Marketo client ID or client secret"),
                (False, "Invalid Marketo client ID or client secret"),
            ),
        ],
    )
    def test_validate_credentials_passes_the_probe_result_through(
        self, probe_result: tuple[bool, Optional[str]], expected: tuple[bool, Optional[str]]
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as probe:
            assert self.source.validate_credentials(self.config, self.team_id) == expected

        probe.assert_called_once_with("123-ABC-456", "client-id", "client-secret")

    def test_get_resumable_source_manager_is_bound_to_the_marketo_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MarketoResumeConfig

    def test_source_for_pipeline_plumbs_config_and_inputs(self) -> None:
        inputs = _make_inputs(
            schema_name="activities",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )
        manager = mock.MagicMock()

        with mock.patch(SOURCE_PATCH) as marketo_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = marketo_source.call_args.kwargs
        assert kwargs["munchkin_id"] == "123-ABC-456"
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["endpoint"] == "activities"
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_a_stale_watermark_on_a_full_refresh(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )

        with mock.patch(SOURCE_PATCH) as marketo_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert marketo_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_are_keyed_by_endpoint_name(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) <= set(ENDPOINTS)
        assert set(descriptions) == set(ENDPOINTS)
        assert all(entry.get("description") for entry in descriptions.values())

    @pytest.mark.parametrize(
        "error_key",
        ["Marketo authentication failed", "Marketo API error 601", "Marketo API error 603", "Marketo API error 607"],
    )
    def test_permanent_failures_disable_the_source_instead_of_retrying(self, error_key: str) -> None:
        errors = self.source.get_non_retryable_errors()

        assert errors[error_key]
