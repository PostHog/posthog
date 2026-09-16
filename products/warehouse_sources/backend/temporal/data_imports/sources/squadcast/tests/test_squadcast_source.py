import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.source import SquadcastSource
from products.warehouse_sources.backend.types import IncrementalFieldType

SQUADCAST_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.squadcast"


class TestSquadcastSource:
    def setup_method(self) -> None:
        self.source = SquadcastSource()
        self.config = MagicMock(refresh_token="refresh_tok", region="us")

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_date_windowed_endpoints_support_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        for name in ("incidents", "postmortems"):
            assert schemas[name].supports_incremental is True, name
            assert schemas[name].incremental_fields[0]["field"] == "created_at"
            assert schemas[name].incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime

        for name in ENDPOINTS:
            if name in ("incidents", "postmortems"):
                continue
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_no_endpoint_supports_append(self) -> None:
        # Incidents and postmortems mutate after creation and window boundaries re-pull rows,
        # so only merge semantics are safe.
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}

    @pytest.mark.parametrize(
        "pattern",
        [
            "Squadcast refresh token was rejected",
            "401 Client Error: Unauthorized for url: https://api.squadcast.com",
            "401 Client Error: Unauthorized for url: https://api.eu.squadcast.com",
            "403 Client Error: Forbidden for url: https://api.squadcast.com",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()

    def test_validate_credentials_success(self) -> None:
        with patch(f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid_token(self) -> None:
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 401, "Invalid Squadcast refresh token"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid Squadcast refresh token"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may only have access to a subset of resources; don't block connection.
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 403, "Your Squadcast account does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{SQUADCAST_MODULE}.source.validate_squadcast_credentials",
            return_value=(False, 403, "Your Squadcast account does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="incidents")
            assert ok is False
            assert error == "Your Squadcast account does not have access to this resource"
