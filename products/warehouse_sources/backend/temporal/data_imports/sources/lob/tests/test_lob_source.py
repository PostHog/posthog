from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lob import LobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.source import LobSource

INCREMENTAL_ENDPOINTS = {"letters", "postcards", "checks", "self_mailers"}
FULL_REFRESH_ENDPOINTS = {"addresses", "bank_accounts", "templates", "campaigns"}


class TestLobGetSchemas:
    def test_all_endpoints_present(self) -> None:
        schemas = LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(sorted(INCREMENTAL_ENDPOINTS))
    def test_incremental_endpoints_support_incremental(self, endpoint: str) -> None:
        schema = next(s for s in LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date_created"]

    @parameterized.expand(sorted(FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoints_do_not_support_incremental(self, endpoint: str) -> None:
        schema = next(s for s in LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []
        assert schema.description == "Full refresh only"

    def test_names_filter(self) -> None:
        schemas = LobSource().get_schemas(LobSourceConfig(api_key="k"), team_id=1, names=["letters"])
        assert [s.name for s in schemas] == ["letters"]


class TestLobValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), None, True),
            ("unauthorized", (False, 401), None, False),
            # A 403 at source-create (no schema) is accepted — the key is real but lacks this scope.
            ("forbidden_at_create", (False, 403), None, True),
            # The same 403 when validating a specific schema is rejected.
            ("forbidden_for_schema", (False, 403), "letters", False),
            ("unknown_error", (False, None), None, False),
        ]
    )
    def test_validate(self, _name: str, probe_result, schema_name, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lob.source.validate_lob_credentials",
            return_value=probe_result,
        ):
            valid, _error = LobSource().validate_credentials(
                LobSourceConfig(api_key="k"), team_id=1, schema_name=schema_name
            )
        assert valid is expected_valid


class TestLobNonRetryableErrors:
    def test_maps_auth_errors(self) -> None:
        errors = LobSource().get_non_retryable_errors()
        keys = " ".join(errors.keys())
        assert "401" in keys
        assert "403" in keys
        assert all(v for v in errors.values())
