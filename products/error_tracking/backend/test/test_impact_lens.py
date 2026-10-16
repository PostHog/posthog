from django.test import SimpleTestCase

from products.error_tracking.backend.logic.recommendations.impact_lens import per_team_results, shared_batch_results


class TestPerTeamResults(SimpleTestCase):
    def setUp(self) -> None:
        self.fetched: list[list[int]] = []

    def _fetch(self, team_ids: list[int]) -> dict[int, str]:
        self.fetched.append(team_ids)
        # Team 3 has no rows, as a team without data does not come back from a query.
        return {team_id: f"rows of {team_id}" for team_id in team_ids if team_id != 3}

    def test_a_batch_queries_each_team_once_per_query_and_window(self) -> None:
        with shared_batch_results():
            first = per_team_results(("page_load", "day"), [1, 2], self._fetch, str)
            second = per_team_results(("page_load", "day"), [2, 3], self._fetch, str)
            other_window = per_team_results(("page_load", "week"), [2], self._fetch, str)

        self.assertEqual(self.fetched, [[1, 2], [3], [2]])
        self.assertEqual(first, {1: "rows of 1", 2: "rows of 2"})
        self.assertEqual(second, {2: "rows of 2", 3: ""})
        self.assertEqual(other_window, {2: "rows of 2"})

    def test_outside_a_batch_every_call_queries(self) -> None:
        per_team_results(("page_load", "day"), [1], self._fetch, str)
        with shared_batch_results():
            pass
        per_team_results(("page_load", "day"), [1], self._fetch, str)

        self.assertEqual(self.fetched, [[1], [1]])
