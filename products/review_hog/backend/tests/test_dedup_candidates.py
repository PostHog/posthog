from parameterized import parameterized

from products.review_hog.backend.reviewer.models.github_meta import PRComment
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.issue_deduplicator import _comment_range, _select_dedup_candidates


def _issue(file: str, start: int, end: int | None = None) -> Issue:
    return Issue(
        id=f"{file}:{start}",
        title="t",
        file=file,
        lines=[LineRange(start=start, end=end)],
        issue="p",
        suggestion="s",
        priority=IssuePriority.SHOULD_FIX,
    )


def _comment(path: str, line: int | None, start_line: int | None = None) -> PRComment:
    return PRComment(path=path, line=line, start_line=start_line, body="b", diff_hunk="@@", user="u", created_at="c")


class TestDedupCandidateSelection:
    # A prior multi-line comment must collide across its WHOLE range: reducing it to its end line
    # let findings inside the commented range (but off that line) skip the LLM dedup and re-post
    # what a reviewer already raised.
    @parameterized.expand(
        [
            ("inside_multiline_range_off_end_line", _comment("a.py", line=20, start_line=10), 12, 14, True),
            ("touching_end_line", _comment("a.py", line=20, start_line=10), 18, 20, True),
            ("single_line_comment_hit", _comment("a.py", line=5), 5, None, True),
            ("outside_range", _comment("a.py", line=20, start_line=10), 30, 31, False),
            ("other_file", _comment("b.py", line=12, start_line=10), 12, 14, False),
        ]
    )
    def test_comment_collision_uses_the_full_range(
        self, _name: str, comment: PRComment, start: int, end: int | None, expect_candidate: bool
    ) -> None:
        issue = _issue("a.py", start, end)
        rng = _comment_range(comment)
        assert rng is not None

        candidates, unique = _select_dedup_candidates([issue], [rng])

        assert (issue in candidates) is expect_candidate
        assert (issue in unique) is not expect_candidate

    def test_comment_without_lines_is_ignored(self) -> None:
        assert _comment_range(_comment("a.py", line=None, start_line=None)) is None
