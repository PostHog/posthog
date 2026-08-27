from parameterized import parameterized

from products.review_hog.backend.reviewer.models.issues_review import LineRange
from products.review_hog.backend.reviewer.outcomes.line_proximity import (
    ComparedFile,
    parse_compare_files,
    touched_near,
    trim_patch_near,
)


def _cf(filename: str, changed: set[int], previous: str | None = None) -> ComparedFile:
    return ComparedFile(filename=filename, previous_filename=previous, changed_base_lines=frozenset(changed))


class TestParseCompareFiles:
    def test_added_and_deleted_lines_map_to_base_side_numbers(self):
        # Base-side numbering is the whole game: a finding's lines are anchored to the compare's base,
        # so a mis-walk (advancing the base counter on an addition, or dropping the addition anchor)
        # shifts every proximity check. Hunk starts at base line 10: context_a is 10, the two additions
        # both anchor at 11 (they consume no base line), context_d is 11, removed_e is 12.
        patch = "@@ -10,3 +10,4 @@ def f():\n context_a\n+added_b\n+added_c\n context_d\n-removed_e\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_base_lines == frozenset({11, 12})

    def test_each_hunk_resets_to_its_base_start(self):
        patch = "@@ -1,1 +1,2 @@\n+a\n b\n@@ -50,1 +51,1 @@\n+z\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_base_lines == frozenset({1, 50})

    def test_content_lines_starting_with_doubled_markers_still_count(self):
        # A deleted markdown frontmatter delimiter arrives as `----` and an added unindented
        # `++title;` as `+++title;`. GitHub's compare `patch` is hunk-only, so a `+++`/`---`
        # file-header guard has nothing to protect against and instead swallows these real changes
        # (the finding never reaches the judge → durably `ignored`) while also mis-walking the
        # base-side counter on the dropped deletion, shifting every later anchor.
        patch = "@@ -1,3 +1,4 @@\n front\n----\n+++title;\n+z\n end\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_base_lines == frozenset({2, 3})

    def test_a_deletion_run_spans_every_line_it_removed(self):
        # Deleting a whole buggy block is a normal way to resolve a finding. Each deleted line
        # consumes a base line, so the run has to register all of them: anchoring the block at its
        # first line alone would put a finding flagged deep inside it outside the proximity window,
        # and a miss there settles as `ignored` without ever reaching the judge.
        patch = "@@ -10,20 +10,0 @@\n" + "".join(f"-dead_{i}\n" for i in range(20))
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_base_lines == frozenset(
            range(10, 30)
        )

    def test_no_newline_marker_is_not_a_line(self):
        patch = "@@ -1,1 +1,1 @@\n+a\n\\ No newline at end of file\n"
        assert parse_compare_files([{"filename": "f.py", "patch": patch}])[0].changed_base_lines == frozenset({1})

    def test_file_without_patch_keeps_rename_but_has_no_changed_lines(self):
        # A binary or pure-rename file carries no patch: it must contribute no proximity yet still map
        # its old name, so a finding on the old path isn't matched as "touched" by an empty change.
        compared = parse_compare_files([{"filename": "new.py", "previous_filename": "old.py"}])[0]
        assert compared.changed_base_lines == frozenset()
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

    def test_nearest_hunk_is_represented_even_when_it_alone_exceeds_the_budget(self):
        # Returning an empty diff would make every oversized case read as "nothing touched it", which
        # is exactly the misclassification the cap must not cause. So the nearest hunk is never
        # dropped — but it is sliced rather than kept whole, or the ceiling would be advisory.
        only = _hunk(900, "y" * 5_000)
        trimmed, dropped = trim_patch_near(only + "\n" + _hunk(10, "x" * 5_000), [LineRange(start=900)], max_chars=100)
        assert len(trimmed) <= 100
        assert trimmed.startswith("@@ -900,")  # the nearest hunk, not the far one
        assert "x" * 5_000 not in trimmed
        assert dropped == 1


def test_a_fix_below_an_added_block_still_reads_as_touched():
    # The reference-frame bug this numbering exists to prevent. A finding sits at line 200 of the file
    # as reviewed. Post-review commits add a 20-line helper up at line 50 and fix the flagged line.
    # On the compare's NEW side that fix lands near 220, which falls outside a +/-15 window around 200
    # and would settle the finding as `ignored` with no judge call — the miss the gate cannot catch.
    # Anchored to the base, the fix is still at 200 whatever landed above it.
    added_block = "@@ -50,1 +50,21 @@\n context\n" + "".join(f"+helper_{i}\n" for i in range(20))
    the_fix = "@@ -200,1 +220,1 @@\n-off_by_one\n+fixed\n"
    compared = parse_compare_files([{"filename": "f.py", "patch": added_block + the_fix}])

    assert touched_near(file="f.py", lines=[LineRange(start=200)], compared=compared, window=15) is True


class TestOversizedSingleHunk:
    def _giant_hunk(self, fix_row: int = 900, rows: int = 2000) -> str:
        body = [f"+filler_{i}" for i in range(rows)]
        body[fix_row] = "+the_fix"
        return f"@@ -1,1 +1,{rows} @@\n" + "\n".join(body)

    def test_one_hunk_larger_than_the_budget_is_still_bounded(self):
        # Hunk sizes are set by whoever wrote the diff. Returning the nearest hunk whole whenever it
        # alone overran the budget made the ceiling advisory: a large enough change next to a finding
        # sets the judge prompt's size, and an oversized prompt the provider rejects leaves the report
        # unstamped, so every later sweep rebuilds the same request.
        trimmed, _ = trim_patch_near(self._giant_hunk(), [LineRange(start=1)], max_chars=2_000)
        assert len(trimmed) <= 2_000

    def test_the_trim_keeps_the_rows_around_the_finding(self):
        # Bounding is only useful if what survives is the evidence. Cutting the string from the front
        # would bound it just as well and leave the judge ruling on rows that decide nothing.
        patch = "@@ -500,1 +500,1 @@\n" + "\n".join(f"+filler_{i}" for i in range(400)) + "\n+the_fix"
        trimmed, _ = trim_patch_near(patch, [LineRange(start=500)], max_chars=1_000)
        assert len(trimmed) <= 1_000
        assert "row(s) of this hunk omitted" in trimmed
