from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.contracts import DEFAULT_DECISION_MODEL, MAX_OPTIONS_PER_QUESTION, MAX_QUESTIONS_PER_REQUEST
from ..facade.enums import DecisionQuestionType, SearchIntentSource

MAX_STATE_CHARS = 65_536
MAX_INSTRUCTIONS_CHARS = 2_000
MAX_OPTION_CHARS = 500


@extend_schema_field(
    {
        "oneOf": [
            {"type": "object", "additionalProperties": {"type": "string"}},
            {"type": "array", "items": {"type": "string"}},
        ]
    }
)
class CriteriaField(serializers.Field):
    def to_internal_value(self, data: Any) -> dict[str, str] | list[str]:
        if isinstance(data, dict) and all(
            isinstance(key, str) and isinstance(value, str) for key, value in data.items()
        ):
            texts = [*data.keys(), *data.values()]
        elif isinstance(data, list) and all(isinstance(value, str) for value in data):
            texts = data
        else:
            raise serializers.ValidationError(
                "Criteria must be an object of option names to meanings, or a list of scale labels."
            )
        if len(data) > MAX_OPTIONS_PER_QUESTION:
            raise serializers.ValidationError(f"A question takes at most {MAX_OPTIONS_PER_QUESTION} options.")
        if any(len(text) > MAX_OPTION_CHARS for text in texts):
            raise serializers.ValidationError(
                f"An option name, meaning or label takes at most {MAX_OPTION_CHARS} characters."
            )
        return data

    def to_representation(self, value: dict[str, str] | list[str]) -> dict[str, str] | list[str]:
        return value


class DecisionQuestionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=DecisionQuestionType.choices,
        help_text="What kind of answer to produce: a yes/no probability, one of the given options, or a rating.",
    )
    instructions = serializers.CharField(
        max_length=MAX_INSTRUCTIONS_CHARS,
        help_text="The question to ask about the state, phrased for the model.",
    )
    criteria = CriteriaField(
        required=False,
        help_text=(
            "For a multiple choice question, the options keyed by name. For a rating question, the scale labels "
            "in order from lowest to highest, at least two. Omitted for a yes/no question."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        criteria = attrs.get("criteria")
        match attrs["type"]:
            case DecisionQuestionType.SCORE if not (isinstance(criteria, list) and len(criteria) >= 2):
                raise serializers.ValidationError({"criteria": "A rating question needs at least two scale labels."})
            case DecisionQuestionType.CHOICE if not (isinstance(criteria, dict) and criteria):
                raise serializers.ValidationError({"criteria": "A multiple choice question needs its options."})
            case DecisionQuestionType.NOUL if isinstance(criteria, list):
                raise serializers.ValidationError({"criteria": "A yes/no question does not take scale labels."})
        return attrs


class DecideRequestSerializer(serializers.Serializer):
    state = serializers.CharField(
        max_length=MAX_STATE_CHARS,
        help_text="The text the questions are about, for example a support ticket or a session summary.",
    )
    questions = serializers.DictField(
        child=DecisionQuestionSerializer(),
        help_text=(
            "The questions to ask, keyed by an id of your choice, at most "
            f"{MAX_QUESTIONS_PER_REQUEST} per request. Answers come back under the same ids."
        ),
    )
    model = serializers.CharField(
        default=DEFAULT_DECISION_MODEL,
        max_length=200,
        help_text="The decision model to ask, as a gateway model id.",
    )

    def validate_questions(self, questions: dict[str, Any]) -> dict[str, Any]:
        if len(questions) > MAX_QUESTIONS_PER_REQUEST:
            raise serializers.ValidationError(f"A request takes at most {MAX_QUESTIONS_PER_REQUEST} questions.")
        return questions


class DecisionAnswerSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=DecisionQuestionType.choices, help_text="The question type answered.")
    probability = serializers.FloatField(
        allow_null=True,
        help_text="For a yes/no question, the probability of yes.",
    )
    choice = serializers.CharField(allow_null=True, help_text="For a multiple choice question, the option chosen.")
    score = serializers.FloatField(allow_null=True, help_text="For a rating question, the expected rating.")
    confidence = serializers.FloatField(
        allow_null=True,
        help_text="How far the chosen option stands out from the rest, from 0 (a coin flip) to 1.",
    )
    probabilities = serializers.DictField(
        child=serializers.FloatField(),
        allow_null=True,
        help_text="For multiple choice and rating questions, the probability of each option.",
    )


class DecideResponseSerializer(serializers.Serializer):
    model = serializers.CharField(help_text="The model that answered, as the serving host names it.")
    answers = serializers.DictField(
        child=DecisionAnswerSerializer(),
        help_text="One answer per question, under the ids the request used.",
    )
    input_tokens = serializers.IntegerField(help_text="Tokens the model read, which is what the request is billed on.")
    latency_ms = serializers.FloatField(allow_null=True, help_text="Time the model spent answering, if reported.")


MAX_SEARCH_QUERY_CHARS = 200
MAX_GROUP_TYPE_CHARS = 100
MAX_GROUP_TYPES = 64


class SearchIntentRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=MAX_SEARCH_QUERY_CHARS,
        allow_blank=True,
        trim_whitespace=True,
        help_text="What the person typed into the filter picker search box.",
    )
    active_group_type = serializers.CharField(
        max_length=MAX_GROUP_TYPE_CHARS,
        help_text="The picker tab that is open, as a taxonomic group type such as event_properties.",
    )
    available_group_types = serializers.ListField(
        child=serializers.CharField(max_length=MAX_GROUP_TYPE_CHARS),
        max_length=MAX_GROUP_TYPES,
        help_text="The taxonomic group types the picker shows. The answer is always one of these, or null.",
    )
    scene = serializers.RegexField(
        r"^[A-Za-z0-9_-]{1,64}$",
        required=False,
        allow_null=True,
        help_text="The id of the scene the picker is open in, such as Insight or Replay.",
    )


class SearchIntentResponseSerializer(serializers.Serializer):
    group_type = serializers.CharField(
        allow_null=True,
        help_text="The taxonomic group type the search most likely belongs to, or null if it was not classified.",
    )
    confidence = serializers.FloatField(
        help_text="How far the chosen group stands out from the rest, from 0 (a coin flip) to 1.",
    )
    is_confident = serializers.BooleanField(
        help_text="Whether the confidence is high enough to act on, for example to suggest a different tab.",
    )
    suggests_switch = serializers.BooleanField(
        help_text="Whether the picker should suggest switching from the open tab to group_type.",
    )
    method = serializers.ChoiceField(
        choices=SearchIntentSource.choices,
        help_text="How the answer was found: a value pattern, the decision model, or not at all.",
    )
