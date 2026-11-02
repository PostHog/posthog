from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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

    @parameterized.expand(
        [
            ("valid", 200, "acme", None, True),
            ("invalid_key", 401, "acme", None, False),
            ("forbidden_at_create", 403, "acme", None, True),
            ("forbidden_for_schema", 403, "acme", "contacts", False),
            ("bad_domain", None, "bad domain", None, False),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int | None,
        domain: str,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        script = [ScriptedResponse(status=status)] if status is not None else []
        with scripted_network(script) as network:
            ok, _error = FreshsalesSource().validate_credentials(
                _config(domain=domain), team_id=1, schema_name=schema_name
            )

        assert ok is expected_ok
        assert len(network.requests_log) == (1 if status is not None else 0)
