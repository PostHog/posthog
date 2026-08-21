from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source import FreshsalesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshsales import (
    FreshsalesSourceConfig,
)


def _config(domain: str = "acme", api_key: str = "key") -> FreshsalesSourceConfig:
    return FreshsalesSourceConfig.from_dict({"domain": domain, "api_key": api_key})


class TestFreshsalesSource:
    def test_connection_host_fields(self) -> None:
        # The API key is sent to a host derived from `domain`, so retargeting it must re-require the key.
        assert FreshsalesSource().connection_host_fields == ["domain"]

    def test_get_schemas_full_refresh_only(self) -> None:
        schemas = FreshsalesSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Freshsales has no verified server-side timestamp filter, so every endpoint is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = FreshsalesSource().get_schemas(_config(), team_id=1, names=["contacts", "deals"])
        assert {s.name for s in schemas} == {"contacts", "deals"}

    @parameterized.expand(
        [
            ("valid", True, None, None, None, True),
            ("invalid_key", False, "Invalid Freshsales API key", 401, None, False),
            ("forbidden_at_create", False, "no scope", 403, None, True),
            ("forbidden_for_schema", False, "no scope", 403, "contacts", False),
            ("bad_domain", False, "Invalid Freshsales domain", None, None, False),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        check_ok: bool,
        check_error: str | None,
        check_status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source.check_credentials",
            return_value=(check_ok, check_error, check_status),
        ):
            ok, _error = FreshsalesSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
