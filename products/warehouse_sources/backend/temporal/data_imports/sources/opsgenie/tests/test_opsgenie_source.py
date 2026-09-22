import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.source import OpsgenieSource
from products.warehouse_sources.backend.types import IncrementalFieldType

OPSGENIE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie"


class TestOpsgenieSource:
    def setup_method(self) -> None:
        self.source = OpsgenieSource()
        self.config = MagicMock(api_key="key_123", region="us")

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_alerts_and_incidents_support_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        for name in ("alerts", "incidents"):
            assert schemas[name].supports_incremental is True, name
            assert schemas[name].incremental_fields[0]["field"] == "createdAt", name
            assert schemas[name].incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime, name

        for name in ENDPOINTS:
            if name in ("alerts", "incidents"):
                continue
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_no_endpoint_supports_append(self) -> None:
        # Opsgenie alerts and incidents mutate after creation (status, acknowledgement),
        # so append-only mode is never offered.
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "users"])
        assert {s.name for s in schemas} == {"alerts", "users"}

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error: Unauthorized for url: https://api.opsgenie.com",
            "403 Client Error: Forbidden for url: https://api.opsgenie.com",
            "401 Client Error: Unauthorized for url: https://api.eu.opsgenie.com",
            "403 Client Error: Forbidden for url: https://api.eu.opsgenie.com",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()

    def test_validate_credentials_success(self) -> None:
        with patch(f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    @pytest.mark.parametrize(
        "status,error",
        [
            (401, "Invalid Opsgenie API key"),
            (422, "Your Opsgenie API key format is not valid"),
        ],
    )
    def test_validate_credentials_invalid_key(self, status: int, error: str) -> None:
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, status, error),
        ):
            ok, returned_error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert returned_error == error

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid key may only have access to a subset of resources (e.g. no Configuration
        # access for integrations); don't block connection.
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, 403, "Your Opsgenie API key does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{OPSGENIE_MODULE}.source.validate_opsgenie_credentials",
            return_value=(False, 403, "Your Opsgenie API key does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="integrations")
            assert ok is False
            assert error == "Your Opsgenie API key does not have access to this resource"
