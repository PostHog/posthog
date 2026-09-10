import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lessannoyingcrm import (
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    ENDPOINTS,
    LESS_ANNOYING_CRM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source import (
    LessAnnoyingCRMSource,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.source"


class TestLessAnnoyingCRMSource:
    def setup_method(self) -> None:
        self.source = LessAnnoyingCRMSource()
        self.team_id = 123
        self.config = LessAnnoyingCRMSourceConfig(api_key="test-key")

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_are_full_refresh_only(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        # LACRM has no server-side modified-since filter, so nothing is incremental.
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.detected_primary_keys == LESS_ANNOYING_CRM_ENDPOINTS[endpoint].primary_keys

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts", "tasks"])
        assert {s.name for s in schemas} == {"contacts", "tasks"}

    def test_validate_credentials_success(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=True):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(f"{MODULE}.validate_less_annoying_crm_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)
