from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User


class TestAdventCalendarAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patch = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _url(self, team: Team, action: str) -> str:
        return f"/api/projects/{team.id}/workflow_advent_calendar/{action}/"

    def _answer_as(self, user: User, team: Team, day: int, option: str) -> Any:
        self.client.force_login(user)
        response = self.client.post(self._url(team, "answer"), {"day": day, "option": option})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _results(self) -> list[dict[str, Any]]:
        self.client.force_login(self.user)
        response = self.client.get(self._url(self.team, "results"))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["questions"]

    def _member_of_another_organization(self, email: str) -> tuple[User, Team]:
        organization = Organization.objects.create(name="Other organization")
        team = Team.objects.create(organization=organization, name="Other project")
        user = User.objects.create_and_join(organization, email, "password")
        return user, team

    def test_results_count_answers_from_every_project_and_show_only_the_callers_own_answers(self) -> None:
        james_fan, other_team = self._member_of_another_organization("james-fan@example.com")
        self._answer_as(james_fan, other_team, 2, "james")
        self._answer_as(james_fan, other_team, 5, "yes")
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        self._answer_as(teammate, self.team, 2, "tim")
        self._answer_as(self.user, self.team, 2, "tim")

        questions = self._results()

        assert [question["day"] for question in questions] == [2, 5, 10, 13, 18, 21]
        results = {question["day"]: question for question in questions}
        assert results[2] == {
            "day": 2,
            "answer": "tim",
            "shares": [{"option": "james", "share": 33}, {"option": "tim", "share": 67}],
        }
        assert results[5] == {
            "day": 5,
            "answer": None,
            "shares": [{"option": "yes", "share": 100}, {"option": "no", "share": 0}],
        }
        assert results[21] == {
            "day": 21,
            "answer": None,
            "shares": [{"option": "coffee", "share": 0}, {"option": "tea", "share": 0}],
        }

    def test_the_first_answer_for_a_day_stands(self) -> None:
        self._answer_as(self.user, self.team, 13, "dark")

        second = self._answer_as(self.user, self.team, 13, "light")

        day_13 = next(question for question in second["questions"] if question["day"] == 13)
        assert day_13 == {
            "day": 13,
            "answer": "dark",
            "shares": [{"option": "dark", "share": 100}, {"option": "light", "share": 0}],
        }

    @parameterized.expand(
        [
            ("day_without_a_question", {"day": 3, "option": "yes"}),
            ("option_of_another_day", {"day": 2, "option": "yes"}),
            ("free_text_option", {"day": 10, "option": "both"}),
            ("missing_option", {"day": 10}),
        ]
    )
    def test_answer_rejects_anything_outside_the_six_questions(self, _name: str, body: dict[str, Any]) -> None:
        response = self.client.post(self._url(self.team, "answer"), body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert all(question["answer"] is None for question in self._results())

    def test_people_outside_the_advent_calendar_rollout_can_neither_answer_nor_read(self) -> None:
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            answer = self.client.post(self._url(self.team, "answer"), {"day": 2, "option": "tim"})
            results = self.client.get(self._url(self.team, "results"))

        assert answer.status_code == status.HTTP_403_FORBIDDEN
        assert results.status_code == status.HTTP_403_FORBIDDEN
        assert all(question["answer"] is None for question in self._results())
