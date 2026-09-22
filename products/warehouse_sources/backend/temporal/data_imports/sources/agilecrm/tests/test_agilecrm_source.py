from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm import source as agilecrm_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.source import AgileCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.agilecrm import (
    AgileCRMSourceConfig,
)


def _config() -> AgileCRMSourceConfig:
    return AgileCRMSourceConfig(domain="acme", email="a@b.com", api_key="key")


class TestSourceConfig:
    def test_domain_is_a_connection_host_field(self) -> None:
        # Retargeting the domain (where the API key is sent) must re-require secrets.
        assert AgileCRMSource().connection_host_fields == ["domain"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://acme.agilecrm.com/dev/api/contacts"),
            ("forbidden", "403 Client Error: Forbidden for url: https://acme.agilecrm.com/dev/api/opportunity"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = AgileCRMSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)


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
        inputs = MagicMock()
        inputs.schema_name = endpoint
        response = AgileCRMSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
