from rest_framework import serializers

from ..facade.contracts import DEFAULT_DECISION_MODEL
from ..facade.enums import DecisionQuestionType


class DecisionQuestionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=DecisionQuestionType.choices,
        help_text="What kind of answer to produce: a yes/no probability, one of the given options, or a rating.",
    )
    instructions = serializers.CharField(
        help_text="The question to ask about the state, phrased for the model.",
    )
    criteria = serializers.DictField(
        child=serializers.CharField(help_text="What this option means."),
        required=False,
        help_text="For a multiple choice question, the options keyed by name. Omitted for other question types.",
    )


class DecideRequestSerializer(serializers.Serializer):
    state = serializers.CharField(
        help_text="The text the questions are about, for example a support ticket or a session summary.",
    )
    questions = serializers.DictField(
        child=DecisionQuestionSerializer(),
        help_text="The questions to ask, keyed by an id of your choice. Answers come back under the same ids.",
    )
    model = serializers.CharField(
        default=DEFAULT_DECISION_MODEL,
        help_text="The decision model to ask, as a gateway model id.",
    )


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
    latency_ms = serializers.IntegerField(allow_null=True, help_text="Time the model spent answering, if reported.")
