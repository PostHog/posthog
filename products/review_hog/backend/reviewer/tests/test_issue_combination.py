from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues


def _issue(issue_id: str) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file=f"src/{issue_id}.py",
        lines=[LineRange(start=10, end=20)],
        issue="A problem",
        suggestion="A fix",
        priority=IssuePriority.MUST_FIX,
    )


class TestCombineIssues:
    def test_stamps_source_lens_per_pass_and_flattens_in_key_order(self) -> None:
        # Passes 1..3 map to PassType members in order; combine flattens sorted by (pass, chunk).
        lens_results = {
            (3, 5): IssuesReview(issues=[_issue("3-5-1")]),
            (1, 5): IssuesReview(issues=[_issue("1-5-1"), _issue("1-5-2")]),
            (2, 5): IssuesReview(issues=[_issue("2-5-1")]),
        }

        combined = combine_issues(lens_results)

        # Total count equals the sum of every review's issues.
        assert len(combined) == 4
        # Deterministic order: sorted by (pass_number, chunk_id), so pass 1 issues come first.
        assert [i.id for i in combined] == ["1-5-1", "1-5-2", "2-5-1", "3-5-1"]
        # Each issue carries the lens value for its pass number.
        expected_lens = {
            "1-5-1": "Logic & Correctness",
            "1-5-2": "Logic & Correctness",
            "2-5-1": "Contracts & Security",
            "3-5-1": "Performance & Reliability",
        }
        assert {i.id: i.source_lens for i in combined} == expected_lens

    def test_orders_by_chunk_id_within_a_pass(self) -> None:
        # Within one pass, chunks flatten in ascending chunk_id order regardless of insertion order.
        lens_results = {
            (1, 5): IssuesReview(issues=[_issue("1-5-1")]),
            (1, 1): IssuesReview(issues=[_issue("1-1-1")]),
            (1, 3): IssuesReview(issues=[_issue("1-3-1")]),
        }

        combined = combine_issues(lens_results)

        assert [i.id for i in combined] == ["1-1-1", "1-3-1", "1-5-1"]

    def test_empty_input_returns_empty_list(self) -> None:
        assert combine_issues({}) == []
