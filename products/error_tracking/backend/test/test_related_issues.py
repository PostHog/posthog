from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.related_issues import PairRow, find_related_issues

TEAM_ID = 1


class TestFindRelatedIssues(SimpleTestCase):
    @parameterized.expand(
        [
            # name, sessions a, sessions b, sessions with both, shared within 5 seconds, a strictly first, b strictly
            # first, expected (lead, relation)
            ("a_causes_b", 30, 42, 30, 30, 30, 0, ("a", "causes")),
            ("b_causes_a", 42, 30, 30, 30, 1, 29, ("b", "causes")),
            ("one_problem_filed_twice", 22, 22, 22, 22, 11, 11, ("a", "same")),
            ("fire_together_without_order", 35, 35, 25, 25, 12, 13, ("a", "together")),
            ("larger_issue_leads_an_undirected_pair", 20, 35, 20, 20, 10, 10, ("b", "together")),
            # Two issues from one throw land in the same millisecond, which says nothing about which leads.
            ("captured_together_from_one_throw", 30, 42, 30, 30, 0, 0, ("b", "together")),
            ("mostly_simultaneous_with_a_few_ordered", 30, 42, 30, 30, 10, 0, ("b", "together")),
            ("too_few_shared_sessions", 14, 14, 14, 14, 14, 0, None),
            ("shared_sessions_are_a_small_part_of_either", 100, 100, 30, 30, 30, 0, None),
            ("in_the_same_sessions_but_far_apart", 40, 40, 40, 10, 10, 0, None),
        ]
    )
    def test_relates_issues_that_fire_close_together(
        self,
        _name: str,
        sessions_a: int,
        sessions_b: int,
        both_sessions: int,
        shared_sessions: int,
        a_first_sessions: int,
        b_first_sessions: int,
        expected: tuple[str, str] | None,
    ) -> None:
        pair_rows = [
            PairRow(
                team_id=TEAM_ID,
                issue_a="a",
                issue_b="b",
                both_sessions=both_sessions,
                shared_sessions=shared_sessions,
                a_first_sessions=a_first_sessions,
                b_first_sessions=b_first_sessions,
            )
        ]
        issue_sessions = {(TEAM_ID, "a"): sessions_a, (TEAM_ID, "b"): sessions_b}

        pairs = find_related_issues(pair_rows, issue_sessions).get(TEAM_ID, [])

        self.assertEqual([(pair["id"], pair["relation"]) for pair in pairs], [expected] if expected else [])
