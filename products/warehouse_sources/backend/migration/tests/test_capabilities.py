from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceCapabilities(SimpleTestCase):
    @parameterized.expand(
        [
            # Lists tables only with credentials, so its known tables come from the canonical descriptions.
            ("google_ads", ExternalDataSourceType.GOOGLEADS, True, frozenset()),
            ("postgres", ExternalDataSourceType.POSTGRES, False, frozenset({"ssh_tunnel"})),
        ]
    )
    def test_capabilities(
        self, _name: str, source_type: ExternalDataSourceType, knows_tables: bool, toggle_groups: frozenset[str]
    ) -> None:
        caps = source_capabilities(source_type)
        assert (caps.documented_tables is not None) == knows_tables
        assert toggle_groups <= caps.toggle_groups
