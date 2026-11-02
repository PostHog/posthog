from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.source import AutomoxSource


class TestSourceConfig:
    def test_connection_host_fields_force_secret_reentry_on_org_change(self) -> None:
        # Changing organization_id retargets the stored API key, so it must count as a host field.
        assert AutomoxSource().connection_host_fields == ["organization_id"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            # Raised by resolve_organization — the message prefixes must stay matchable.
            ("org_not_found", f"{ORG_NOT_FOUND_ERROR}: no organization with ID 999 is accessible with this API key"),
            (
                "multiple_orgs",
                f"{MULTIPLE_ORGS_ERROR}: set the organization ID on the source to pick which one to sync",
            ),
        ]
    )
    def test_permanent_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = AutomoxSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
