from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.event.util import bulk_create_events

from products.access_control.backend.models.access_control import AccessControl
from products.surveys.backend.facade.api import LinkedSurveyResponses, RatingScale, get_survey_responses_linked_to
from products.surveys.backend.models import Survey, SurveyResponseArchive

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
QUESTIONS: list[dict[str, object]] = [
    {"id": "q-thumbs", "type": "rating", "question": "Was this answer useful?", "scale": 2, "display": "emoji"},
    {
        "id": "q-score",
        "type": "rating",
        "question": "How good was it?",
        "scale": 5,
        "display": "number",
        "lowerBoundLabel": "Bad",
        "upperBoundLabel": "Great",
    },
    {"id": "q-topic", "type": "single_choice", "question": "What was it about?", "choices": ["Billing", "Setup"]},
    {
        "id": "q-issues",
        "type": "multiple_choice",
        "question": "What could be better?",
        "choices": ["Accuracy", "Tone", "Length"],
    },
    {"id": "q-comment", "type": "open", "question": "Anything else?"},
]


class TestLinkedSurveyResponses(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.survey = Survey.objects.create(team=self.team, name="Answer quality", type="api", questions=QUESTIONS)

    def _event(
        self,
        event: str,
        *,
        survey_id: str | None = None,
        minute: int = 1,
        trace_id: str = "trace-1",
        uuid: str | None = None,
        properties: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "event": event,
            "event_uuid": uuid or str(uuid4()),
            "distinct_id": "user-1",
            "team": self.team,
            "timestamp": T0 + timedelta(minutes=minute),
            "properties": {
                "$survey_id": survey_id or str(self.survey.id),
                "$ai_trace_id": trace_id,
                **(properties or {}),
            },
        }

    def _read(self, user_given: bool = True) -> LinkedSurveyResponses:
        return get_survey_responses_linked_to(
            self.team,
            self.user if user_given else None,
            property_name="$ai_trace_id",
            property_value="trace-1",
            since=T0,
        )

    def _answers(self, linked: LinkedSurveyResponses) -> list[list[tuple[str, object]]]:
        return [[(answer.question_id, answer.value) for answer in response.answers] for response in linked.responses]

    def test_merges_a_submission_split_across_events(self) -> None:
        bulk_create_events(
            [
                self._event(
                    "survey sent",
                    minute=1,
                    properties={
                        "$survey_submission_id": "sub-1",
                        "$survey_response_q-score": "4",
                        "$survey_completed": False,
                    },
                ),
                self._event(
                    "survey dismissed",
                    minute=2,
                    properties={
                        "$survey_submission_id": "sub-1",
                        "$survey_response_q-comment": "Too long, but correct.",
                        "$survey_partially_completed": True,
                    },
                ),
            ]
        )

        linked = self._read()

        assert self._answers(linked) == [[("q-score", "4"), ("q-comment", "Too long, but correct.")]]
        assert [(response.submission_id, response.complete) for response in linked.responses] == [("sub-1", False)]

    @parameterized.expand(
        [
            ("one survey sent without a completion flag", [("survey sent", {})], True),
            (
                "an incomplete send, then a completed send",
                [("survey sent", {"$survey_completed": False}), ("survey sent", {"$survey_completed": True})],
                True,
            ),
            (
                "an incomplete send, then a partial dismissal",
                [
                    ("survey sent", {"$survey_completed": False}),
                    ("survey dismissed", {"$survey_partially_completed": True}),
                ],
                False,
            ),
        ]
    )
    def test_complete(self, _name: str, events: list[tuple[str, dict[str, object]]], expected: bool) -> None:
        bulk_create_events(
            [
                self._event(
                    event,
                    minute=index + 1,
                    properties={"$survey_submission_id": "sub-1", "$survey_response_q-comment": "Fine.", **properties},
                )
                for index, (event, properties) in enumerate(events)
            ]
        )

        assert [response.complete for response in self._read().responses] == [expected]

    def test_keeps_repeat_submissions_apart(self) -> None:
        bulk_create_events(
            [
                self._event(
                    "survey sent",
                    minute=1,
                    properties={"$survey_submission_id": "sub-1", "$survey_response_q-score": "2"},
                ),
                self._event(
                    "survey sent",
                    minute=2,
                    properties={"$survey_submission_id": "sub-2", "$survey_response_q-score": "5"},
                ),
            ]
        )

        assert self._answers(self._read()) == [[("q-score", "2")], [("q-score", "5")]]

    def test_events_without_a_submission_id_are_each_a_response(self) -> None:
        first, second = str(uuid4()), str(uuid4())
        bulk_create_events(
            [
                self._event("survey sent", minute=1, uuid=first, properties={"$survey_response_q-score": "3"}),
                self._event("survey sent", minute=2, uuid=second, properties={"$survey_response_q-score": "4"}),
            ]
        )

        assert [response.submission_id for response in self._read().responses] == [first, second]

    def test_reads_only_events_linked_to_the_value_since_the_start(self) -> None:
        bulk_create_events(
            [
                self._event("survey sent", minute=1, properties={"$survey_response_q-comment": "Linked."}),
                self._event(
                    "survey sent", minute=2, trace_id="trace-2", properties={"$survey_response_q-comment": "Other."}
                ),
                self._event("survey sent", minute=-5, properties={"$survey_response_q-comment": "Too early."}),
            ]
        )

        assert self._answers(self._read()) == [[("q-comment", "Linked.")]]

    def test_matches_a_survey_id_written_in_upper_case(self) -> None:
        bulk_create_events(
            [
                self._event(
                    "survey sent",
                    survey_id=str(self.survey.id).upper(),
                    properties={"$survey_response_q-comment": "Upper."},
                )
            ]
        )

        linked = self._read()

        assert [(response.survey.id, response.survey.name) for response in linked.responses] == [
            (str(self.survey.id), "Answer quality")
        ]

    def test_reads_every_kind_of_answer_with_its_question(self) -> None:
        bulk_create_events(
            [
                self._event(
                    "survey sent",
                    properties={
                        "$survey_response_q-thumbs": "1",
                        "$survey_response_q-score": "4",
                        "$survey_response_q-topic": "Billing",
                        "$survey_response_q-issues": ["Accuracy", "Tone"],
                        "$survey_response_q-comment": "Too long, but correct.",
                    },
                )
            ]
        )

        [response] = self._read().responses

        assert [
            (answer.question_text, answer.question_type, answer.value, answer.rating) for answer in response.answers
        ] == [
            (
                "Was this answer useful?",
                "rating",
                "1",
                RatingScale(scale=2, display="emoji", lower_bound_label=None, upper_bound_label=None),
            ),
            (
                "How good was it?",
                "rating",
                "4",
                RatingScale(scale=5, display="number", lower_bound_label="Bad", upper_bound_label="Great"),
            ),
            ("What was it about?", "single_choice", "Billing", None),
            ("What could be better?", "multiple_choice", ("Accuracy", "Tone"), None),
            ("Anything else?", "open", "Too long, but correct.", None),
        ]

    def test_maps_translated_choices_back_to_the_base_language(self) -> None:
        translated = Survey.objects.create(
            team=self.team,
            name="Answer quality, translated",
            type="api",
            questions=[
                {**QUESTIONS[2], "translations": {"fr": {"choices": ["Facturation", "Installation"]}}},
                {**QUESTIONS[3], "translations": {"fr": {"choices": ["Exactitude", "Ton", "Longueur"]}}},
            ],
        )
        bulk_create_events(
            [
                self._event(
                    "survey sent",
                    survey_id=str(translated.id),
                    properties={"$survey_response_q-topic": "Facturation", "$survey_response_q-issues": ["Ton"]},
                )
            ]
        )

        assert self._answers(self._read()) == [[("q-topic", "Billing"), ("q-issues", ("Tone",))]]

    def test_reports_a_response_to_a_missing_survey(self) -> None:
        missing = str(uuid4())
        bulk_create_events([self._event("survey sent", survey_id=missing, properties={"$survey_response": "Hi."})])

        [response] = self._read().responses

        assert (response.survey.id, response.survey.name, response.answers, response.unavailable) == (
            missing,
            None,
            (),
            "survey_not_found",
        )

    def test_reports_a_survey_without_questions(self) -> None:
        empty = Survey.objects.create(team=self.team, name="Empty", type="api", questions=[])
        bulk_create_events([self._event("survey sent", survey_id=str(empty.id))])

        assert [(response.survey.name, response.unavailable) for response in self._read().responses] == [
            ("Empty", "no_questions")
        ]

    def test_a_shown_survey_without_a_response_is_unanswered(self) -> None:
        shown_only = Survey.objects.create(team=self.team, name="Follow-up", type="api", questions=QUESTIONS)
        bulk_create_events(
            [
                self._event("survey shown", minute=1),
                self._event("survey sent", minute=2, properties={"$survey_response_q-comment": "Fine."}),
                self._event("survey shown", survey_id=str(shown_only.id), minute=3),
                self._event("survey shown", survey_id=str(shown_only.id), minute=4),
            ]
        )

        linked = self._read()

        assert [(survey.survey.name, survey.shown_at) for survey in linked.unanswered] == [
            ("Follow-up", T0 + timedelta(minutes=3))
        ]
        assert [response.survey.name for response in linked.responses] == ["Answer quality"]

    def test_omits_surveys_the_viewer_cannot_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="survey", access_level="none", organization_member=self.organization_membership
        )
        bulk_create_events(
            [
                self._event("survey sent", minute=1, properties={"$survey_response_q-comment": "Hidden."}),
                self._event("survey shown", minute=2),
            ]
        )

        assert self._read() == LinkedSurveyResponses(responses=(), unanswered=())
        assert len(self._read(user_given=False).responses) == 1

    def test_excludes_archived_responses(self) -> None:
        archived, kept = str(uuid4()), str(uuid4())
        bulk_create_events(
            [
                self._event("survey sent", minute=1, uuid=archived, properties={"$survey_response_q-comment": "Old."}),
                self._event("survey sent", minute=2, uuid=kept, properties={"$survey_response_q-comment": "New."}),
            ]
        )
        SurveyResponseArchive.objects.create(team=self.team, survey=self.survey, response_uuid=archived)

        assert self._answers(self._read()) == [[("q-comment", "New.")]]
