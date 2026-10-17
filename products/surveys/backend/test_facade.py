import uuid
from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from products.product_tours.backend.models import ProductTour
from products.surveys.backend.facade.api import SurveyResponses, list_running_survey_responses
from products.surveys.backend.models import Survey, SurveyResponseArchive


class TestListRunningSurveyResponses(ClickhouseTestMixin, BaseTest):
    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    def _survey(self, name: str, **fields: object) -> Survey:
        return Survey.objects.create(
            **{
                "team": self.team,
                "name": name,
                "type": "popover",
                "created_by": self.user,
                "start_date": self._ago(30),
                **fields,
            }
        )

    def _response(
        self,
        survey: Survey,
        days_ago: int,
        submission_id: str | None,
        event: str = "survey sent",
        partial: bool = False,
    ) -> str:
        properties: dict[str, object] = {"$survey_id": str(survey.id)}
        if submission_id:
            properties["$survey_submission_id"] = submission_id
        if partial:
            properties["$survey_partially_completed"] = "true"
        return _create_event(
            team=self.team,
            event=event,
            distinct_id=str(uuid.uuid4()),
            properties=properties,
            timestamp=self._ago(days_ago),
        )

    def test_counts_unique_responses_of_your_running_surveys_this_week_and_last_week(self) -> None:
        running = self._survey("Onboarding feedback")
        self._survey("Ended", end_date=self._ago(1))
        self._survey("Draft", start_date=None)
        self._survey("Archived", archived=True)
        self._survey("Not yours", created_by=self._create_user("other@example.com"))
        tour_step = self._survey("Tour step")
        ProductTour.objects.create(team=self.team, name="Welcome tour").linked_surveys.add(tour_step)
        self._response(running, 1, "submission-a")
        self._response(running, 2, "submission-a")
        self._response(running, 2, "submission-b")
        self._response(running, 3, None)
        self._response(running, 3, "submission-e", event="survey dismissed", partial=True)
        self._response(running, 3, "submission-f", event="survey dismissed")
        self._response(running, 10, "submission-c")
        self._response(running, 20, "submission-d")
        self._response(running, 9, "submission-g")
        for archived in (self._response(running, 2, None), self._response(running, 2, "submission-g")):
            SurveyResponseArchive.objects.create(team=self.team, survey=running, response_uuid=archived)
        flush_persons_and_events()

        assert list_running_survey_responses(self.team, self.user, limit=20) == [
            SurveyResponses(survey_id=running.id, name="Onboarding feedback", this_week=4, last_week=1)
        ]

    @parameterized.expand([("smaller_uuid_first", False), ("larger_uuid_first", True)])
    def test_leaves_out_an_archived_submission_whose_events_share_a_timestamp(
        self, _name: str, larger_first: bool
    ) -> None:
        survey = self._survey("Onboarding feedback")
        at = self._ago(1)
        smaller, larger = "00000000-0000-4000-8000-000000000001", "ffffffff-ffff-4fff-bfff-ffffffffffff"
        for event_uuid in (larger, smaller) if larger_first else (smaller, larger):
            _create_event(
                team=self.team,
                event="survey sent",
                distinct_id="person",
                event_uuid=event_uuid,
                properties={"$survey_id": str(survey.id), "$survey_submission_id": "submission-a"},
                timestamp=at,
            )
        SurveyResponseArchive.objects.create(team=self.team, survey=survey, response_uuid=larger)
        flush_persons_and_events()

        assert list_running_survey_responses(self.team, self.user, limit=20) == [
            SurveyResponses(survey_id=survey.id, name="Onboarding feedback", this_week=0, last_week=0)
        ]
