from types import SimpleNamespace
from typing import cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.powerbiadmin import (
    PowerBiAdminSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin import (
    ADMIN_API_DENIED_ERROR,
    PowerBiAdminResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.settings import (
    ACTIVITY_EVENTS_ENDPOINT,
    ENDPOINTS,
    POWER_BI_ADMIN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.source import PowerBiAdminSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.source"

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_SECRET = "super-secret"


def _inputs(
    schema_name: str = ACTIVITY_EVENTS_ENDPOINT,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
) -> SourceInputs:
    return cast(
        SourceInputs,
        SimpleNamespace(
            schema_name=schema_name,
            schema_id="schema-1",
            source_id="source-1",
            team_id=123,
            job_id="job-1",
            logger=mock.MagicMock(),
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="CreationTime" if should_use_incremental_field else None,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
    )


class TestPowerBiAdminSource:
    def setup_method(self) -> None:
        self.source = PowerBiAdminSource()
        self.team_id = 123
        self.config = PowerBiAdminSourceConfig(tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.POWERBIADMIN

    def test_tenant_id_is_a_connection_host_field(self) -> None:
        # Retargeting the tenant ID must force re-entry of the client secret — without this an
        # editor could repoint a preserved secret at another Entra directory.
        assert self.source.connection_host_fields == ["tenant_id"]

    def test_get_source_config_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.name.value == "PowerBiAdmin"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.iconPath == "/static/services/power_bi_admin.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/power-bi-admin"

    def test_config_asks_the_customer_for_the_service_principal(self) -> None:
        fields_by_name = {field.name: field for field in self.source.get_source_config.fields}

        assert set(fields_by_name) == {"tenant_id", "client_id", "client_secret"}
        for field in fields_by_name.values():
            assert isinstance(field, SourceFieldInputConfig)
            assert field.required is True

        secret = fields_by_name["client_secret"]
        assert isinstance(secret, SourceFieldInputConfig)
        assert secret.secret is True
        assert secret.type.value == "password"
        assert cast(SourceFieldInputConfig, fields_by_name["tenant_id"]).secret is False

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.description == POWER_BI_ADMIN_ENDPOINTS[schema.name].description

    def test_only_activity_events_support_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        activity = schemas[ACTIVITY_EVENTS_ENDPOINT]
        assert activity.supports_incremental is True
        assert {field["field"] for field in activity.incremental_fields} == {"CreationTime"}

        for name, schema in schemas.items():
            if name == ACTIVITY_EVENTS_ENDPOINT:
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["groups"])
        assert [schema.name for schema in schemas] == ["groups"]

    def test_non_retryable_errors_cover_token_and_admin_denials(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert ADMIN_API_DENIED_ERROR in errors
        assert errors["403 Client Error: Forbidden for url: https://api.powerbi.com"] == ADMIN_API_DENIED_ERROR
        assert "401 Client Error: Unauthorized for url: https://login.microsoftonline.com" in errors

    @parameterized.expand([(True, None), (False, "nope")])
    @mock.patch(f"{MODULE}.validate_power_bi_admin_credentials")
    def test_validate_credentials_plumbs_the_service_principal(
        self, expected_valid: bool, expected_message: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = (expected_valid, expected_message)

        assert self.source.validate_credentials(self.config, self.team_id) == (expected_valid, expected_message)
        mock_validate.assert_called_once_with(tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs(schema_name="groups"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PowerBiAdminResumeConfig
        # Activity-event day cursors and OData offsets must not share a Redis slot.
        assert manager._key.endswith(":groups")

    @mock.patch(f"{MODULE}.power_bi_admin_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_source: mock.MagicMock) -> None:
        mock_source.return_value = SimpleNamespace(name=ACTIVITY_EVENTS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(should_use_incremental_field=True, db_incremental_field_last_value="2026-07-20T00:00:00Z")

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            endpoint=ACTIVITY_EVENTS_ENDPOINT,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-20T00:00:00Z",
        )
        assert response is mock_source.return_value

    @mock.patch(f"{MODULE}.power_bi_admin_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        mock_source.return_value = SimpleNamespace(name="groups")
        inputs = _inputs(
            schema_name="groups", should_use_incremental_field=False, db_incremental_field_last_value="2026-07-20"
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://learn.microsoft.com/")
            # Every primary key must be documented, since that is the column users join on.
            assert set(POWER_BI_ADMIN_ENDPOINTS[name].primary_keys) <= set(entry["columns"])

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        for table in tables:
            assert table["description"]
        activity = next(table for table in tables if table["name"] == ACTIVITY_EVENTS_ENDPOINT)
        assert "Incremental" in activity["sync_methods"]
