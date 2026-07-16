from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.types import (
    resolve_detected_primary_keys,
)


class TestResolveDetectedPrimaryKeys:
    @parameterized.expand(
        [
            # Driver-discovered keys always win over the name fallback.
            ("discovered_wins", ["pk"], [("id", "integer", False)], ["pk"]),
            ("id_fallback", None, [("name", "text", True), ("id", "integer", False)], ["id"]),
            # Snowflake uppercases unquoted identifiers: match `ID` case-insensitively and return
            # the actual stored casing — the merge indexes batches by the real column name.
            ("uppercase_id_matched_with_actual_casing", None, [("ID", "text", False)], ["ID"]),
            ("no_id_column", None, [("name", "text", True)], None),
        ]
    )
    def test_fallback(self, _name, discovered, columns, expected):
        assert resolve_detected_primary_keys(discovered, columns) == expected
