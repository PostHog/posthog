from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pardot import PardotSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.pardot import PardotResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARDOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source import PardotSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = sorted(INCREMENTAL_FIELDS)
FULL_REFRESH_ENDPOINTS = sorted(set(ENDPOINTS) - set(INCREMENTAL_FIELDS))


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
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestPardotSource:
    def setup_method(self) -> None:
        self.source = PardotSource()
        self.team_id = 123
        self.config = PardotSourceConfig(
            business_unit_id="0Uv000000000000000",
            client_id="3MVG9",
            client_secret="secret",
            refresh_token="refresh",
            environment="production",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PARDOT

    def test_get_source_config_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.label == "Pardot"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/pardot.png"

    def test_source_config_collects_the_salesforce_oauth_credentials(self) -> None:
        fields = {field.name: field for field in self.source.get_source_config.fields}

        assert set(fields) == {"environment", "business_unit_id", "client_id", "client_secret", "refresh_token"}

        environment = fields["environment"]
        assert isinstance(environment, SourceFieldSelectConfig)
        assert [option.value for option in environment.options] == ["production", "sandbox"]

    @pytest.mark.parametrize(
        "field_name, expected_type, expected_secret",
        [
            ("business_unit_id", SourceFieldInputConfigType.TEXT, False),
            ("client_id", SourceFieldInputConfigType.TEXT, False),
            ("client_secret", SourceFieldInputConfigType.PASSWORD, True),
            ("refresh_token", SourceFieldInputConfigType.PASSWORD, True),
        ],
    )
    def test_credential_fields_are_required_and_secrets_masked(
        self, field_name: str, expected_type: SourceFieldInputConfigType, expected_secret: bool
    ) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == field_name)

        assert isinstance(field, SourceFieldInputConfig)
        assert field.required is True
        assert field.type == expected_type
        assert field.secret is expected_secret

    def test_api_version_defaults_to_the_path_the_transport_calls(self) -> None:
        assert self.source.default_version == "v5"
        assert self.source.supported_versions == ("v5",)
        assert self.source.resolve_api_version(None) == "v5"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://pi.pardot.com/api/v5/objects/prospects",
            "403 Client Error: Forbidden for url: https://pi.pardot.com/api/v5/objects/prospects",
            "400 Client Error: Bad Request for url: https://login.salesforce.com/services/oauth2/token",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_advertise_both_timestamps(self, name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == name)

        assert schema.supports_incremental is True
        assert {f["field"] for f in schema.incremental_fields} == {"createdAt", "updatedAt"}

    @pytest.mark.parametrize("name", FULL_REFRESH_ENDPOINTS)
    def test_endpoints_without_a_server_side_filter_stay_full_refresh(self, name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == name)

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["prospects", "campaigns"])

        assert {s.name for s in schemas} == {"prospects", "campaigns"}

    def test_get_schemas_needs_no_credentials(self) -> None:
        # `lists_tables_without_credentials` promises the public docs can list tables from a
        # placeholder config — that only holds while get_schemas does no I/O.
        assert self.source.lists_tables_without_credentials is True
        empty_config = PardotSourceConfig(
            business_unit_id="", client_id="", client_secret="", refresh_token="", environment="production"
        )

        assert {s.name for s in self.source.get_schemas(empty_config, self.team_id)} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "probe_result",
        [(True, None), (False, "Account Engagement rejected the credentials")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.validate_pardot_credentials"
    )
    def test_validate_credentials_passes_through_the_probe(
        self, mock_validate: mock.MagicMock, probe_result: tuple[bool, str | None]
    ) -> None:
        mock_validate.return_value = probe_result

        assert self.source.validate_credentials(self.config, self.team_id) == probe_result
        mock_validate.assert_called_once_with(
            environment="production",
            business_unit_id="0Uv000000000000000",
            client_id="3MVG9",
            client_secret="secret",
            refresh_token="refresh",
        )

    def test_resume_state_is_namespaced_per_endpoint(self) -> None:
        prospects = self.source.get_resumable_source_manager(_make_inputs("prospects"))
        visits = self.source.get_resumable_source_manager(_make_inputs("visits"))

        assert isinstance(prospects, ResumableSourceManager)
        assert prospects._data_class is PardotResumeConfig
        assert prospects._key != visits._key

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.pardot_source")
    def test_source_for_pipeline_forwards_the_incremental_cursor(self, mock_pardot_source: mock.MagicMock) -> None:
        manager = mock.MagicMock()
        inputs = _make_inputs(
            "prospects",
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_pardot_source.call_args.kwargs
        assert kwargs["endpoint"] == "prospects"
        assert kwargs["api_version"] == "v5"
        assert kwargs["incremental_field"] == "updatedAt"
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pardot.source.pardot_source")
    def test_full_refresh_run_drops_the_stored_watermark(self, mock_pardot_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            "prospects", should_use_incremental_field=False, db_incremental_field_last_value="2024-05-01T00:00:00Z"
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pardot_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_descriptions_cover_the_endpoints_they_key_on(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_documented_columns_exist_on_the_endpoint(self, endpoint: str) -> None:
        described = set(CANONICAL_DESCRIPTIONS[endpoint].get("columns", {}))

        assert described <= set(PARDOT_ENDPOINTS[endpoint].fields)
