from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm import source as agilecrm_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.source import AgileCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.agilecrm import (
    AgileCRMSourceConfig,
)


def _config() -> AgileCRMSourceConfig:
    return AgileCRMSourceConfig(domain="acme", email="a@b.com", api_key="key")


class TestSourceConfig:
    def test_domain_is_a_connection_host_field(self) -> None:
        # Retargeting the domain (where the API key is sent) must re-require secrets.
        assert AgileCRMSource().connection_host_fields == ["domain"]


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: True)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: False)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None


class TestPipelinePlumbing:
    @parameterized.expand(
        [
            # Top-level list endpoints keyed on their own id.
            ("contacts", "contacts", ["id"]),
            ("tickets", "tickets", ["id"]),
            # Fan-out children carry the parent id in their composite key so rows stay unique table-wide.
            ("contact_notes", "contact_notes", ["contact_id", "id"]),
            ("ticket_notes", "ticket_notes", ["ticket_id", "id"]),
        ]
    )
    def test_source_for_pipeline_routes_endpoint(self, _name: str, endpoint: str, expected_keys: list[str]) -> None:
        result = SourceDriver(AgileCRMSource(), _config()).run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
