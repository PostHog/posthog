from parameterized import parameterized

from products.review_hog.backend.reviewer.models.issues_review import LineRange
from products.review_hog.backend.reviewer.outcomes.line_proximity import (
    ComparedFile,
    parse_compare_files,
    touched_near,
    trim_patch_near,
)


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


def _hunk(start: int, body: str) -> str:
    return f"@@ -{start},1 +{start},1 @@\n+{body}"


class TestTrimPatchNear:
    def test_under_budget_is_returned_untouched(self):
        patch = _hunk(10, "a") + "\n" + _hunk(500, "b")
        assert trim_patch_near(patch, [LineRange(start=10)], max_chars=10_000) == (patch, 0)

    def test_keeps_the_hunk_nearest_the_finding_not_the_first_one(self):
        # The whole point of trimming by proximity: a blind head-truncation would keep the far hunk
        # and drop the one that made this finding a candidate, leaving the judge to rule on an
        # unrelated change and durably misclassify the finding.
        far = _hunk(10, "x" * 400)
        near = _hunk(900, "y" * 400)
        trimmed, dropped = trim_patch_near(far + "\n" + near, [LineRange(start=900)], max_chars=500)
        assert "y" * 400 in trimmed
        assert "x" * 400 not in trimmed
        assert dropped == 1

    def test_nearest_hunk_is_kept_even_when_it_alone_exceeds_the_budget(self):
        # Evidence beats the ceiling: returning an empty diff would make every oversized case read
        # as "nothing touched it", which is exactly the misclassification the cap must not cause.
        only = _hunk(900, "y" * 5_000)
        trimmed, dropped = trim_patch_near(only + "\n" + _hunk(10, "x" * 5_000), [LineRange(start=900)], max_chars=100)
        assert "y" * 5_000 in trimmed
        assert dropped == 1
