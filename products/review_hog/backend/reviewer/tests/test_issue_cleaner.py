"""Tests for the issue cleaner tool."""

from parameterized import parameterized

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.issue_cleaner import (
    _build_modified_files_map,
    _is_issue_in_scope,
    _parse_issue_lines,
    clean_issues,
)


def _issue(file: str, lines: list[LineRange], issue_id: str = "1-1-1") -> Issue:
    return Issue(
        id=issue_id,
        title="t",
        file=file,
        lines=lines,
        issue="i",
        suggestion="s",
        priority=IssuePriority.SHOULD_FIX,
    )


def _pr_file(
    filename: str, ranges: list[tuple[int, int]], status: str = "modified", change_type: str = "addition"
) -> PRFile:
    return PRFile(
        filename=filename,
        status=status,
        additions=5,
        deletions=2,
        changes=[
            PRFileUpdate(type=change_type, new_start_line=start, new_end_line=end, code="x") for start, end in ranges
        ],
    )


# All scope decisions are made against a single file changed on lines 10-20.
_PR_FILES = [_pr_file("app/main.py", [(10, 20)])]


class TestCleanIssuesScope:
    @parameterized.expand(
        [
            # (name, file, lines, expected_in_scope)
            ("fully_contained", "app/main.py", [LineRange(start=15, end=18)], True),
            ("partial_overlap", "app/main.py", [LineRange(start=18, end=25)], True),
            ("touching_edge", "app/main.py", [LineRange(start=20, end=30)], True),
            ("envelops_change", "app/main.py", [LineRange(start=5, end=40)], True),
            ("single_line_inside", "app/main.py", [LineRange(start=15, end=None)], True),
            ("single_line_outside", "app/main.py", [LineRange(start=100, end=None)], False),
            ("below_change", "app/main.py", [LineRange(start=50, end=60)], False),
            ("wrong_file", "app/other.py", [LineRange(start=15, end=18)], False),
            # No line ranges -> in scope as long as the file matches.
            ("no_lines_file_match", "app/main.py", [], True),
            ("no_lines_wrong_file", "app/other.py", [], False),
        ]
    )
    def test_clean_issues_in_scope_filtering(
        self, _name: str, file: str, lines: list[LineRange], expected_in_scope: bool
    ) -> None:
        result = clean_issues([_issue(file, lines)], _PR_FILES)
        assert (len(result) == 1) is expected_in_scope

    def test_clean_issues_keeps_only_in_scope_across_files(self) -> None:
        # main.py and utils.py are changed; other.py is untouched.
        issues = [
            _issue("app/main.py", [LineRange(start=15, end=18)], "a"),
            _issue("app/utils.py", [LineRange(start=25, end=30)], "b"),
            _issue("app/other.py", [LineRange(start=10, end=20)], "c"),
        ]
        pr_files = [
            _pr_file("app/main.py", [(10, 20)]),
            _pr_file("app/utils.py", [(20, 35)]),
        ]
        result = clean_issues(issues, pr_files)
        assert {i.id for i in result} == {"a", "b"}

    def test_clean_issues_overlaps_any_of_multiple_change_ranges(self) -> None:
        # A file with disjoint change ranges; an issue overlapping any single range is in scope.
        pr_files = [_pr_file("app/main.py", [(112, 112), (213, 213), (217, 223)])]
        issues = [
            _issue("app/main.py", [LineRange(start=213, end=223)], "spans-split"),
            _issue("app/main.py", [LineRange(start=205, end=226)], "envelops-block"),
            _issue("app/main.py", [LineRange(start=111, end=113)], "spans-single"),
            _issue("app/main.py", [LineRange(start=300, end=310)], "no-overlap"),
        ]
        result = clean_issues(issues, pr_files)
        assert {i.id for i in result} == {"spans-split", "envelops-block", "spans-single"}


class TestBuildModifiedFilesMap:
    @parameterized.expand(
        [
            # Status never excludes a file — renamed/copied files carry real diffs too; files
            # without addition changes (e.g. pure renames) are excluded by the empty-ranges guard.
            ("modified", "modified"),
            ("added", "added"),
            ("renamed", "renamed"),
            ("copied", "copied"),
        ]
    )
    def test_includes_any_status_with_addition_changes(self, _name: str, status: str) -> None:
        assert _build_modified_files_map([_pr_file("f.py", [(1, 5)], status=status)]) == {"f.py": [(1, 5)]}

    @parameterized.expand(
        [
            ("addition", "addition", True),
            # context/deletion changes don't define a reviewable changed range.
            ("context", "context", False),
            ("deletion", "deletion", False),
        ]
    )
    def test_change_type_filtering(self, _name: str, change_type: str, included: bool) -> None:
        result = _build_modified_files_map([_pr_file("f.py", [(1, 5)], change_type=change_type)])
        assert result == ({"f.py": [(1, 5)]} if included else {})

    def test_skips_changes_missing_new_line_numbers(self) -> None:
        # A change with no new line numbers can't be located in the new file, so the file is dropped.
        pr_file = PRFile(
            filename="f.py",
            status="modified",
            additions=1,
            deletions=0,
            changes=[PRFileUpdate(type="addition", code="x")],
        )
        assert _build_modified_files_map([pr_file]) == {}


class TestParseIssueLines:
    @parameterized.expand(
        [
            ("single_line_collapses_to_pair", [LineRange(start=10, end=None)], [(10, 10)]),
            ("multi_line_preserved", [LineRange(start=10, end=20)], [(10, 20)]),
            ("empty", [], []),
            (
                "multiple_ranges",
                [LineRange(start=1, end=2), LineRange(start=5, end=None)],
                [(1, 2), (5, 5)],
            ),
        ]
    )
    def test_parse_issue_lines(self, _name: str, lines: list[LineRange], expected: list[tuple[int, int]]) -> None:
        assert _parse_issue_lines(_issue("f.py", lines)) == expected


class TestIsIssueInScope:
    def test_file_not_in_map_is_out_of_scope(self) -> None:
        assert _is_issue_in_scope(_issue("missing.py", [LineRange(start=1, end=2)]), {"f.py": [(1, 5)]}) is False

    def test_file_match_with_no_lines_is_in_scope(self) -> None:
        assert _is_issue_in_scope(_issue("f.py", []), {"f.py": [(1, 5)]}) is True
