from typing import Any, Optional

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.outreach import (
    OutreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.outreach import OutreachResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.source import OutreachSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.outreach.source.validate_outreach_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.outreach.source.outreach_source"


def _make_inputs(schema_name: str = "prospects", **overrides: Any) -> mock.MagicMock:
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


class TestOutreachSource:
    def setup_method(self) -> None:
        self.source = OutreachSource()
        self.team_id = 123
        self.config = OutreachSourceConfig(client_id="client-id", client_secret="client-secret", refresh_token="rt")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.OUTREACH

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Outreach"
        assert config.label == "Outreach"
        assert config.category == DataWarehouseSourceCategory.SALES
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Held back from the catalog until a PostHog-owned Outreach credential exists; a pasted
        # refresh token cannot survive Outreach's rotation.
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/outreach.png"

    @pytest.mark.parametrize(
        "name,required,secret",
        [
            ("client_id", True, False),
            ("client_secret", True, True),
            ("refresh_token", True, True),
        ],
    )
    def test_source_fields(self, name: str, required: bool, secret: bool) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert len(fields) == 3
        assert fields[name].required is required
        assert bool(fields[name].secret) is secret

    def test_secret_fields_use_password_input_type(self) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert fields["client_secret"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["refresh_token"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["client_id"].type == SourceFieldInputConfigType.TEXT

    def test_api_docs_url_and_public_table_listing(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")
        # get_schemas iterates a static catalog with no I/O, so the docs can render the tables.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_the_whole_endpoint_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert sorted(schema.name for schema in schemas) == sorted(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["prospects", "accounts"])

        assert sorted(schema.name for schema in schemas) == ["accounts", "prospects"]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_endpoint_supports_the_updatedat_incremental_filter(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [field["field"] for field in schema.incremental_fields] == ["updatedAt"]

    @pytest.mark.parametrize(
        "probe_result,expected",
        [
            (True, (True, None)),
            (False, (False, "Invalid Outreach credentials")),
        ],
    )
    def test_validate_credentials_passes_the_probe_result_through(
        self, probe_result: bool, expected: tuple[bool, Optional[str]]
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as probe:
            assert self.source.validate_credentials(self.config, self.team_id) == expected

        probe.assert_called_once_with("client-id", "client-secret", "rt")

    def test_get_resumable_source_manager_is_bound_to_the_outreach_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OutreachResumeConfig

    def test_source_for_pipeline_plumbs_config_and_inputs(self) -> None:
        inputs = _make_inputs(
            schema_name="sequenceStates",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )
        manager = mock.MagicMock()

        with mock.patch(SOURCE_PATCH) as outreach_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = outreach_source.call_args.kwargs
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["refresh_token"] == "rt"
        assert kwargs["endpoint"] == "sequenceStates"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_a_stale_watermark_on_a_full_refresh(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )

        with mock.patch(SOURCE_PATCH) as outreach_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert outreach_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_are_keyed_by_endpoint_name(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        assert all(entry.get("description") for entry in descriptions.values())

    @pytest.mark.parametrize(
        "error_key",
        [
            "400 Client Error: Bad Request for url: https://api.outreach.io/oauth/token",
            "401 Client Error: Unauthorized for url: https://api.outreach.io/oauth/token",
        ],
    )
    def test_permanent_token_failures_disable_the_source_instead_of_retrying(self, error_key: str) -> None:
        errors = self.source.get_non_retryable_errors()

        assert errors[error_key]

    def test_a_401_on_the_api_host_is_not_treated_as_permanent(self) -> None:
        # Mid-sync 401s on the API host (not the token endpoint) are handled by token re-mint.
        # The keys are substring patterns, matched against the raised message by the runtime
        # (see `error_message_matches`), so match the message against them rather than looking
        # the message up as a dict key - a key lookup would pass for any prefix pattern too.
        error_msg = "401 Client Error: Unauthorized for url: https://api.outreach.io/api/v2/prospects"
        errors = self.source.get_non_retryable_errors()

        assert not any(pattern in error_msg for pattern in errors)
