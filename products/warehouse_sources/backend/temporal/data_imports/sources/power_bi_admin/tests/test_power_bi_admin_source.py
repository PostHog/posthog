from types import SimpleNamespace
from typing import cast

from unittest import mock

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

    def test_tenant_id_is_a_connection_host_field(self) -> None:
        # Retargeting the tenant ID must force re-entry of the client secret — without this an
        # editor could repoint a preserved secret at another Entra directory.
        assert self.source.connection_host_fields == ["tenant_id"]

    def test_non_retryable_errors_cover_token_and_admin_denials(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert ADMIN_API_DENIED_ERROR in errors
        assert errors["403 Client Error: Forbidden for url: https://api.powerbi.com"] == ADMIN_API_DENIED_ERROR
        assert "401 Client Error: Unauthorized for url: https://login.microsoftonline.com" in errors

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs(schema_name="groups"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PowerBiAdminResumeConfig
        # Activity-event day cursors and OData offsets must not share a Redis slot.
        assert manager._key.endswith(":groups")

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://learn.microsoft.com/")
            # Every primary key must be documented, since that is the column users join on.
            assert set(POWER_BI_ADMIN_ENDPOINTS[name].primary_keys) <= set(entry["columns"])
