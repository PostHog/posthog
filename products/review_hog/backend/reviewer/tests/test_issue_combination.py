from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues


def _issue(issue_id: str, source_perspective: str | None = None) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file=f"src/{issue_id}.py",
        lines=[LineRange(start=10, end=20)],
        issue="A problem",
        suggestion="A fix",
        priority=IssuePriority.MUST_FIX,
        source_perspective=source_perspective,
    )


class TestCombineIssues:
    def test_preserves_review_time_source_perspective_and_flattens_in_key_order(self) -> None:
        # source_perspective is stamped (to the skill name) by the review activity, NOT recomputed here —
        # combine must preserve it while re-stamping ids and flattening sorted by (pass, chunk).
        perspective_results = {
            (3, 5): IssuesReview(issues=[_issue("a", "review-hog-perspective-performance-reliability")]),
            (1, 5): IssuesReview(
                issues=[
                    _issue("b", "review-hog-perspective-logic-correctness"),
                    _issue("c", "review-hog-perspective-logic-correctness"),
                ]
            ),
            (2, 5): IssuesReview(issues=[_issue("d", "review-hog-perspective-contracts-security")]),
        }

        combined = combine_issues(perspective_results)

        assert len(combined) == 4
        # Deterministic order: sorted by (pass_number, chunk_id), so pass 1 issues come first.
        assert [i.id for i in combined] == ["1-5-1", "1-5-2", "2-5-1", "3-5-1"]
        # Each issue keeps the skill name its review activity stamped (now keyed by the re-stamped id).
        assert {i.id: i.source_perspective for i in combined} == {
            "1-5-1": "review-hog-perspective-logic-correctness",
            "1-5-2": "review-hog-perspective-logic-correctness",
            "2-5-1": "review-hog-perspective-contracts-security",
            "3-5-1": "review-hog-perspective-performance-reliability",
        }

    def test_orders_by_chunk_id_within_a_pass(self) -> None:
        # Within one pass, chunks flatten in ascending chunk_id order regardless of insertion order.
        perspective_results = {
            (1, 5): IssuesReview(issues=[_issue("1-5-1")]),
            (1, 1): IssuesReview(issues=[_issue("1-1-1")]),
            (1, 3): IssuesReview(issues=[_issue("1-3-1")]),
        }

        combined = combine_issues(perspective_results)

        assert [i.id for i in combined] == ["1-1-1", "1-3-1", "1-5-1"]

    def test_restamps_colliding_agent_ids_to_unique_ids(self) -> None:
        # The perspective-agnostic prompt makes every perspective self-assign "1-..." ids, so findings
        # from different perspectives on the same chunk collide. combine must re-stamp each id from its
        # loop position so validate_issues (which keys verdicts by issue.id) doesn't collapse them.
        perspective_results = {
            (1, 1): IssuesReview(issues=[_issue("1-1-1")]),
            (2, 1): IssuesReview(issues=[_issue("1-1-1")]),
            (3, 1): IssuesReview(issues=[_issue("1-1-1"), _issue("1-1-1")]),
        }

        combined = combine_issues(perspective_results)

        ids = [i.id for i in combined]
        assert ids == ["1-1-1", "2-1-1", "3-1-1", "3-1-2"]
        assert len(set(ids)) == len(ids)

    def test_empty_input_returns_empty_list(self) -> None:
        assert combine_issues({}) == []
