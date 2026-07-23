from parameterized import parameterized

from products.review_hog.backend.reviewer.models.issues_review import LineRange
from products.review_hog.backend.reviewer.outcomes.line_proximity import ComparedFile, parse_compare_files, touched_near


def _cf(filename: str, changed: set[int], previous: str | None = None) -> ComparedFile:
    return ComparedFile(filename=filename, previous_filename=previous, changed_new_lines=frozenset(changed))


class TestParseCompareFiles:
    def test_added_and_deleted_lines_map_to_new_side_numbers(self):
        # New-side line numbering is the whole game: a mis-walk (counting deletions as advancing the
        # new counter, or dropping the deletion anchor) shifts every proximity check off by the number
        # of deletions above it. Hunk starts at new line 10: two additions at 11/12, a deletion anchored
        # at 14 (the context line 13 only advances the counter).
        patch = "@@ -10,3 +10,4 @@ def f():\n context_a\n+added_b\n+added_c\n context_d\n-removed_e\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_new_lines == frozenset(
            {11, 12, 14}
        )

    def test_each_hunk_resets_to_its_new_start(self):
        patch = "@@ -1,1 +1,2 @@\n+a\n b\n@@ -50,1 +51,1 @@\n+z\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_new_lines == frozenset({1, 51})

    def test_content_lines_starting_with_doubled_markers_still_count(self):
        # A deleted markdown frontmatter delimiter arrives as `----` and an added unindented
        # `++title;` as `+++title;`. GitHub's compare `patch` is hunk-only, so a `+++`/`---`
        # file-header guard has nothing to protect against and instead swallows these real changes
        # (the finding never reaches the judge → durably `ignored`) while also advancing the
        # new-side counter on the dropped deletion, shifting every later anchor (+z would land on 4).
        patch = "@@ -1,3 +1,4 @@\n front\n----\n+++title;\n+z\n end\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_new_lines == frozenset({2, 3})

    def test_no_newline_marker_is_not_a_line(self):
        patch = "@@ -1,1 +1,1 @@\n+a\n\\ No newline at end of file\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_new_lines == frozenset({1})

    def test_file_without_patch_keeps_rename_but_has_no_changed_lines(self):
        # A binary or pure-rename file carries no patch: it must contribute no proximity yet still map
        # its old name, so a finding on the old path isn't matched as "touched" by an empty change.
        compared = parse_compare_files([{"filename": "new.py", "previous_filename": "old.py"}])[0]
        assert compared.changed_new_lines == frozenset()
        assert compared.previous_filename == "old.py"


class TestTouchedNear:
    @parameterized.expand(
        [
            ("within_window", [LineRange(start=20)], [_cf("f.py", {30})], 15, True),
            ("outside_window", [LineRange(start=20)], [_cf("f.py", {40})], 15, False),
            ("exact_line_zero_window", [LineRange(start=30)], [_cf("f.py", {30})], 0, True),
            ("range_end_extends_reach", [LineRange(start=10, end=20)], [_cf("f.py", {33})], 15, True),
            ("different_file_never_near", [LineRange(start=30)], [_cf("other.py", {30})], 15, False),
            ("no_line_ranges_never_near", [], [_cf("f.py", {30})], 15, False),
        ]
    )
    def test_touched_near(self, _name, lines, compared, window, expected):
        assert touched_near(file="f.py", lines=lines, compared=compared, window=window) is expected

    def test_matches_renamed_file_by_previous_name(self):
        # The finding was written against the old path; the compare shows the new name. Missing the
        # previous_filename bridge would drop every finding on a since-renamed file to "ignored".
        compared = [_cf("new_name.py", {30}, previous="f.py")]
        assert touched_near(file="f.py", lines=[LineRange(start=30)], compared=compared, window=5) is True
