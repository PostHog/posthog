from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceCapabilities(SimpleTestCase):
    @parameterized.expand(
        [
            # Its canonical descriptions cover only two tables; the real ones are the user's collections.
            ("firebase", ExternalDataSourceType.FIREBASE, False, False, frozenset(), frozenset()),
            ("google_ads", ExternalDataSourceType.GOOGLEADS, False, False, frozenset(), frozenset()),
            # Discovery lists no columns, so apply cannot exclude any.
            ("hubspot", ExternalDataSourceType.HUBSPOT, True, False, frozenset(), frozenset()),
            ("instagram", ExternalDataSourceType.INSTAGRAM, True, False, frozenset(), frozenset({"dwh-instagram"})),
            ("postgres", ExternalDataSourceType.POSTGRES, False, True, frozenset({"ssh_tunnel"}), frozenset()),
        ]
    )
    def test_capabilities(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        knows_tables: bool,
        column_selection: bool,
        toggle_groups: frozenset[str],
        feature_flags: frozenset[str],
    ) -> None:
        caps = source_capabilities(source_type)
        assert (caps.documented_tables is not None) == knows_tables
        assert caps.supports_column_selection == column_selection
        assert toggle_groups <= caps.toggle_groups
        assert caps.feature_flags == feature_flags
