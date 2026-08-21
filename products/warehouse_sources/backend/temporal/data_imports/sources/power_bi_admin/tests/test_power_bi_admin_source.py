from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.powerbiadmin import (
    PowerBiAdminSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin import (
    ADMIN_API_DENIED_ERROR,
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


class TestPowerBiAdminSource:
    def setup_method(self) -> None:
        self.source = PowerBiAdminSource()
        self.team_id = 123
        self.config = PowerBiAdminSourceConfig(tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

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

    def test_non_retryable_errors_cover_token_and_admin_denials(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert ADMIN_API_DENIED_ERROR in errors
        assert errors["403 Client Error: Forbidden for url: https://api.powerbi.com"] == ADMIN_API_DENIED_ERROR
        assert "401 Client Error: Unauthorized for url: https://login.microsoftonline.com" in errors

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://learn.microsoft.com/")
            # Every primary key must be documented, since that is the column users join on.
            assert set(POWER_BI_ADMIN_ENDPOINTS[name].primary_keys) <= set(entry["columns"])
