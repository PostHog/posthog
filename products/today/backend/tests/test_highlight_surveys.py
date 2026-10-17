import uuid
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.surveys.backend.facade.api import SurveyResponses
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import surveys
from products.today.backend.logic.highlight_types import Context


class TestSurveys(SimpleTestCase):
    @parameterized.expand(
        [
            ("first responses", 5, 0, True),
            ("at least one and a half times last week", 6, 4, True),
            ("not enough growth", 6, 5, False),
            ("too few responses", 4, 0, False),
        ]
    )
    def test_a_survey_shows_when_its_responses_jump(
        self, _name: str, this_week: int, last_week: int, shown: bool
    ) -> None:
        survey = SurveyResponses(
            survey_id=uuid.uuid4(), name="Onboarding feedback", this_week=this_week, last_week=last_week
        )
        context = cast(Context, SimpleNamespace(team=None, user=None))
        registered = next(s for s in load_sources() if s.name == "surveys")

        with patch.object(surveys, "list_running_survey_responses", return_value=[survey]):
            found = registered.find(context)

        expected = (
            [
                (
                    f"Survey ‘Onboarding feedback’ received {this_week} responses in the last 7 days",
                    f"{last_week} → {this_week}",
                    f"/surveys/{survey.survey_id}",
                )
            ]
            if shown
            else []
        )
        self.assertEqual([(c.title, c.detail, c.url) for c in found.items], expected)
