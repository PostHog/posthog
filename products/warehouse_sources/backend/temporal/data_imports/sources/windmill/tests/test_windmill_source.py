import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.windmill import (
    WindmillSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source import WindmillSource

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"


class TestWindmillSource:
    def setup_method(self):
        self.source = WindmillSource()
        self.team_id = 123
        self.config = WindmillSourceConfig(host=BASE_URL, workspace=WORKSPACE, api_token="token")

    def test_connection_host_fields_force_token_reentry_on_host_change(self):
        # host receives the api_token, so editing it must re-require the token (no exfiltration
        # of the stored bearer token to an attacker-controlled host).
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.windmill.dev/api/w/my-workspace/scripts/list",
            "403 Client Error: Forbidden for url: https://app.windmill.dev/api/w/my-workspace/audit/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only completed_jobs exposes a genuine server-side timestamp filter.
        assert incremental == {"completed_jobs"}

    def test_completed_jobs_advertises_both_cursor_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["completed_jobs"].incremental_fields == INCREMENTAL_FIELDS["completed_jobs"]
        assert {f["field"] for f in schemas["completed_jobs"].incremental_fields} == {"created_at", "started_at"}
        assert schemas["scripts"].incremental_fields == []
        assert schemas["scripts"].supports_append is False

    def test_audit_logs_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        # Audit logs are EE-only and admin-gated, so they must not be selected by default.
        assert schemas["audit_logs"].should_sync_default is False
        assert schemas["completed_jobs"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["scripts"])
        assert [s.name for s in schemas] == ["scripts"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
