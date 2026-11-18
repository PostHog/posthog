from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceCapabilities(SimpleTestCase):
    @parameterized.expand(
        [
            # Discovery lists no columns, so apply cannot exclude any.
            ("hubspot", ExternalDataSourceType.HUBSPOT, False, False, frozenset(), frozenset()),
            ("instagram", ExternalDataSourceType.INSTAGRAM, False, False, frozenset(), frozenset({"dwh-instagram"})),
            ("postgres", ExternalDataSourceType.POSTGRES, True, False, frozenset({"ssh_tunnel"}), frozenset()),
            # Its HogQL tables read fixed columns, so no column can ever be turned off.
            ("stripe", ExternalDataSourceType.STRIPE, False, True, frozenset(), frozenset()),
        ]
    )
    def test_capabilities(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        column_selection: bool,
        fixed_columns: bool,
        toggle_groups: frozenset[str],
        feature_flags: frozenset[str],
    ) -> None:
        caps = source_capabilities(source_type)
        assert caps.supports_column_selection == column_selection
        assert caps.fixed_columns == fixed_columns
        assert toggle_groups <= caps.toggle_groups
        assert caps.feature_flags == feature_flags
