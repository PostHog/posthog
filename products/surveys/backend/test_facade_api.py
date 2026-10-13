import pytest
from posthog.test.base import BaseTest

from products.product_tours.backend.models import ProductTour
from products.surveys.backend.facade.api import SurveyNotFound, launch_survey, stop_survey
from products.surveys.backend.models import Survey


class TestSurveyLifecycleFacade(BaseTest):
    def test_a_product_tour_survey_is_not_launchable_or_stoppable(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Rate this step", type="api", created_by=self.user)
        tour = ProductTour.objects.create(team=self.team, name="Onboarding tour", content={"steps": []})
        tour.linked_surveys.add(survey)

        with pytest.raises(SurveyNotFound):
            launch_survey(team_id=self.team.id, user_id=self.user.id, survey_id=survey.id)
        with pytest.raises(SurveyNotFound):
            stop_survey(team_id=self.team.id, user_id=self.user.id, survey_id=survey.id)

        survey.refresh_from_db()
        assert survey.start_date is None
        assert survey.end_date is None

    def test_a_standalone_survey_launches_and_stops(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Checkout feedback", type="popover", created_by=self.user)

        launched = launch_survey(team_id=self.team.id, user_id=self.user.id, survey_id=survey.id)
        stopped = stop_survey(team_id=self.team.id, user_id=self.user.id, survey_id=survey.id)

        assert launched.start_date is not None
        assert stopped.end_date is not None
