from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceCapabilities(SimpleTestCase):
    @parameterized.expand(
        [
            # Discovery lists no columns, so apply cannot exclude any.
            ("hubspot", ExternalDataSourceType.HUBSPOT, False, frozenset(), frozenset()),
            ("instagram", ExternalDataSourceType.INSTAGRAM, False, frozenset(), frozenset({"dwh-instagram"})),
            ("postgres", ExternalDataSourceType.POSTGRES, True, frozenset({"ssh_tunnel"}), frozenset()),
        ]
    )
    def test_capabilities(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        column_selection: bool,
        toggle_groups: frozenset[str],
        feature_flags: frozenset[str],
    ) -> None:
        caps = source_capabilities(source_type)
        assert caps.supports_column_selection == column_selection
        assert toggle_groups <= caps.toggle_groups
        assert caps.feature_flags == feature_flags
