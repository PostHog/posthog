from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    ClickHouseGlob,
    compile_clickhouse_glob,
    glob_key_prefix,
    glob_listing_prefix,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import _State


class TestClickHouseGlob:
    @parameterized.expand(
        [
            ("star_stays_in_its_folder", "data/*.csv", "data/a.csv", True),
            ("star_matches_empty", "data/*.csv", "data/.csv", True),
            ("star_does_not_cross_folders", "data/*.csv", "data/2024/a.csv", False),
            ("double_star_crosses_folders", "data/**.csv", "data/2024/01/a.csv", True),
            ("double_star_folder", "data/**", "data/x/y", True),
            ("question_mark_is_one_character", "part-?.csv", "part-1.csv", True),
            ("question_mark_is_not_two", "part-?.csv", "part-10.csv", False),
            ("question_mark_does_not_match_slash", "a?b", "a/b", False),
            ("alternatives", "{orders,refunds}.csv", "refunds.csv", True),
            ("alternatives_are_literal", "{a.b,c}.csv", "aXb.csv", False),
            ("range", "part-{1..12}.csv", "part-12.csv", True),
            ("range_upper_bound", "part-{1..12}.csv", "part-13.csv", False),
            ("range_reversed_bounds", "part-{12..1}.csv", "part-5.csv", True),
            ("range_without_padding_refuses_leading_zero", "part-{1..12}.csv", "part-05.csv", False),
            ("padded_range", "part-{01..12}.csv", "part-05.csv", True),
            ("padded_range_refuses_unpadded", "part-{01..12}.csv", "part-5.csv", False),
            ("literal_regex_characters", "a+b(1).csv", "a+b(1).csv", True),
            ("literal_dot_is_not_any_character", "a.csv", "aXcsv", False),
            ("literal_path_is_exact", "data/a.csv", "data/a.csv.bak", False),
            ("hidden_files_match_like_clickhouse", "data/*", "data/_SUCCESS", True),
            ("range_leaves_digits_for_star", "part-{1..12}*.csv", "part-123.csv", True),
            ("range_does_not_take_extra_digits", "part-{1..12}.csv", "part-123.csv", False),
            ("empty_alternative", "{a,}x.csv", "x.csv", True),
            ("padded_range_in_middle", "d={01..31}/h-*.csv", "d=07/h-1.csv", True),
            ("padded_range_in_middle_refuses_unpadded", "d={01..31}/h-*.csv", "d=7/h-1.csv", False),
            ("zero_range", "{0..0}", "0", True),
            ("zero_range_refuses_extra_zero", "{0..0}", "00", False),
            ("double_star_after_range", "{1..12}**.csv", "123/nested/a.csv", True),
            ("alternatives_before_star", "{a,ab}*.csv", "abc.csv", True),
            ("double_star_matches_empty", "**", "", True),
            ("star_does_not_match_slash", "*", "/", False),
            ("question_mark_does_not_match_only_slash", "?", "/", False),
            ("triple_star_crosses_folders", "***", "a/b", True),
            ("four_stars_match_empty", "****", "", True),
            ("adjacent_empty_alternatives", "*{a,}{b,}x", "x", True),
            ("range_leaves_digits_for_literal", "{1..12}3", "123", True),
            ("padded_reversed_range", "{12..01}", "07", True),
            ("padded_range_uses_widest_bound", "{0..0012}", "0007", True),
        ]
    )
    def test_matches(self, _name: str, pattern: str, path: str, expected: bool) -> None:
        assert compile_clickhouse_glob(pattern).matches(path) is expected

    @parameterized.expand(
        [
            ("unclosed_brace", "a{b,c.csv"),
            ("empty_braces", "a{}.csv"),
            ("nested_glob_in_braces", "{a*,b}.csv"),
            ("square_brackets", "part-[0-9].csv"),
            ("stray_closing_brace", "a}.csv"),
            ("nested_question_mark", "{a?,b}.csv"),
            ("nested_brace", "{{a,b},c}.csv"),
            ("bracket_in_braces", "{a[,b}.csv"),
            ("closing_bracket_in_braces", "{a],b}.csv"),
            ("stray_closing_bracket", "a].csv"),
            ("too_long", "a" * 1025),
            ("too_many_wildcards", "*a" * 65),
            ("too_many_alternatives", "{" + ",".join(str(n) for n in range(65)) + "}"),
        ]
    )
    def test_refuses_patterns_it_cant_read(self, _name: str, pattern: str) -> None:
        with pytest.raises(ObjectStorageError):
            compile_clickhouse_glob(pattern)

    @parameterized.expand(
        [
            ("glob_in_file_name", "events/2024/*.csv", "events/2024"),
            ("glob_in_folder", "events/*/a.csv", "events"),
            ("glob_at_root", "*.csv", ""),
            ("range_folder", "y={2023..2024}/a.parquet", ""),
            ("literal_file", "events/a.csv", "events/a.csv"),
        ]
    )
    def test_listing_prefix(self, _name: str, pattern: str, expected: str) -> None:
        assert glob_listing_prefix(pattern) == expected

    @parameterized.expand(
        [
            ("glob_in_file_name", "exports/orders-*.csv", "exports/orders-"),
            ("glob_at_root", "*.csv", ""),
            ("range_folder", "y={2023..2024}/a.parquet", "y="),
            ("literal_file", "events/a.csv", "events/a.csv"),
            ("question_mark", "a?b", "a"),
        ]
    )
    def test_key_prefix(self, _name: str, pattern: str, expected: str) -> None:
        assert glob_key_prefix(pattern) == expected

    @parameterized.expand(
        [
            ("twenty_stars", "*a" * 20 + "*b.csv"),
            ("eight_stars", "*a*a*a*a*a*a*a*a*b.csv"),
        ]
    )
    def test_adversarial_match_work_is_bounded(self, _name: str, pattern: str) -> None:
        glob = compile_clickhouse_glob(pattern)
        # Short enough that a backtracking matcher returns and fails the assertions below instead of hanging.
        path = "a" * 20 + ".csv"
        closure = ClickHouseGlob._epsilon_closure
        state_counts: list[int] = []

        def counting_closure(self: ClickHouseGlob, states: set[_State]) -> set[_State]:
            result = closure(self, states)
            state_counts.append(len(result))
            return result

        with patch.object(ClickHouseGlob, "_epsilon_closure", counting_closure):
            assert glob.matches(path) is False

        # One state set per character, each no larger than the token count, keeps the work linear.
        assert 0 < len(state_counts) <= len(path) + 1
        assert max(state_counts) <= len(glob.tokens) + 1
        assert glob.matches("a" * 20 + "b.csv") is True

    def test_a_run_of_stars_is_one_wildcard(self) -> None:
        glob = compile_clickhouse_glob("*" * 1000 + ".csv")

        assert len(glob.tokens) == 5
        assert glob.matches("a/b/c.csv") is True
