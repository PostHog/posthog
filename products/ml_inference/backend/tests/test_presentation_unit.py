from django.test import SimpleTestCase

from parameterized import parameterized

from products.ml_inference.backend.presentation.serializers import DecideRequestSerializer

QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "queue": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "money", "support": "product"}},
}


class TestDecideRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("score_with_a_scale", "score", ["calm", "irritated", "angry"], True),
            ("score_with_options_keyed_by_name", "score", {"calm": "not upset"}, False),
            ("score_with_one_label", "score", ["calm"], False),
            ("choice_with_a_list", "choice", ["billing", "support"], False),
            ("choice_without_options", "choice", None, False),
            ("noul_with_a_list", "noul", ["yes", "no"], False),
            ("noul_without_criteria", "noul", None, True),
        ]
    )
    def test_criteria_shape_follows_the_question_type(self, _name, question_type, criteria, valid) -> None:
        question = {"type": question_type, "instructions": "How is it?"}
        if criteria is not None:
            question["criteria"] = criteria
        serializer = DecideRequestSerializer(data={"state": "text", "questions": {"q": question}})

        assert serializer.is_valid() == valid, serializer.errors

    def test_rejects_an_unknown_question_type(self) -> None:
        serializer = DecideRequestSerializer(
            data={"state": "text", "questions": {"q": {"type": "essay", "instructions": "Write one"}}}
        )

        assert not serializer.is_valid()
        assert "questions" in serializer.errors

    def test_caps_the_number_of_questions(self) -> None:
        too_many = {f"q{i}": {"type": "noul", "instructions": "Is it?"} for i in range(33)}
        serializer = DecideRequestSerializer(data={"state": "text", "questions": too_many})

        assert not serializer.is_valid()
        assert "questions" in serializer.errors

    @parameterized.expand(
        [
            ("state", {"state": "x" * 65_537, "questions": QUESTIONS}),
            ("instructions", {"state": "text", "questions": {"q": {"type": "noul", "instructions": "x" * 2_001}}}),
            (
                "option_count",
                {
                    "state": "text",
                    "questions": {
                        "q": {"type": "choice", "instructions": "?", "criteria": {str(i): "m" for i in range(17)}}
                    },
                },
            ),
            (
                "option_length",
                {
                    "state": "text",
                    "questions": {"q": {"type": "score", "instructions": "?", "criteria": ["low", "x" * 501]}},
                },
            ),
        ]
    )
    def test_bounds_the_size_of_every_text_field(self, _name, data) -> None:
        serializer = DecideRequestSerializer(data=data)

        assert not serializer.is_valid()

    def test_defaults_the_model(self) -> None:
        serializer = DecideRequestSerializer(data={"state": "text", "questions": QUESTIONS})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["model"] == "posthog/hogference/jevk5-fp8-0.2"
