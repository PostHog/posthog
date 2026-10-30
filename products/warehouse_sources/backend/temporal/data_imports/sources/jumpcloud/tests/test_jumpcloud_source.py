from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource


class TestSourceConfig:
    def test_connection_host_fields_force_secret_reentry_on_retarget(self) -> None:
        # Changing org_id or region retargets the stored API key (different organization's
        # data, or a different regional host), so both must force re-entering the key.
        assert JumpcloudSource().connection_host_fields == ["org_id", "region"]


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
