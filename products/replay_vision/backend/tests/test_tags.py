from parameterized import parameterized

from products.replay_vision.backend.tags import clickhouse_slugify_sql, slugify_tag


class TestSlugifyTag:
    @parameterized.expand(
        [
            ("title_case", "Frustrated Or Confused", "frustrated_or_confused"),
            ("already_slug", "abandoned", "abandoned"),
            ("upper", "RAGE", "rage"),
            ("runs_of_specials", "Rage!!  Click??", "rage_click"),
            ("leading_trailing_specials", "  --rage--  ", "--rage--"),
            ("leading_trailing_underscores", "__rage__", "rage"),
            ("preserves_internal_dash", "rage-click", "rage-click"),
            ("all_special_collapses_to_empty", "!!! ???", ""),
            ("empty", "", ""),
            ("unicode_stripped", "café déjà", "caf_d_j"),
        ]
    )
    def test_slugify_tag(self, _name: str, value: str, expected: str) -> None:
        assert slugify_tag(value) == expected

    def test_clickhouse_mirror_uses_shared_patterns(self) -> None:
        # The SQL mirror is generated for an arbitrary column expression and embeds the same collapse/strip
        # patterns `slugify_tag` uses, so the two normalizations stay in lockstep.
        sql = clickhouse_slugify_sql("t")
        assert "lower(t)" in sql
        assert "[^a-z0-9_-]+" in sql
        assert "^_+|_+$" in sql
