from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.swarmia import (
    SwarmiaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source import SwarmiaSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source"


class TestSwarmiaSource:
    def setup_method(self) -> None:
        self.source = SwarmiaSource()
        self.config = SwarmiaSourceConfig(api_key="token")

    @parameterized.expand(
        [
            ("pull_requests", True),
            ("dora", True),
            ("investment", True),
            ("capex", False),
            ("capex_employees", False),
            ("fte", False),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        # Re-pulled trailing windows must be merged (deduped on primary key), never appended.
        assert schema.supports_append is False
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["end_date"]

    def test_get_schemas_returns_all_endpoints_and_filters_by_name(self) -> None:
        assert {s.name for s in self.source.get_schemas(self.config, team_id=1)} == set(ENDPOINTS)
        assert [s.name for s in self.source.get_schemas(self.config, team_id=1, names=["dora"])] == ["dora"]

    @parameterized.expand(
        [
            ("valid_token", 200, None, True),
            ("invalid_token", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_fails", 403, "investment", False),
            ("network_failure", None, None, False),
        ]
    )
    @patch(f"{_SOURCE_MODULE}.check_credentials")
    def test_validate_credentials(
        self,
        _name: str,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        mock_check: MagicMock,
    ) -> None:
        mock_check.return_value = status

        valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if not expected_valid:
            assert error

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized for url: https://app.swarmia.com" in errors
        assert "403 Client Error: Forbidden for url: https://app.swarmia.com" in errors

    def test_canonical_descriptions_match_endpoint_catalog(self) -> None:
        # A canonical entry keyed off a name not in the catalog is silently unused (typo guard).
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
