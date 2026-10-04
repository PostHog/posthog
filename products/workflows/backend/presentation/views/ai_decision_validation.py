from typing import Any

from rest_framework import serializers

from products.ml_inference.backend.facade.contracts import MAX_OPTIONS_PER_QUESTION
from products.workflows.backend.facade.enums import AIDecisionAnswerType

MIN_OPTIONS = 2
MAX_CONTEXT_FIELD_NAME_LENGTH = 100

# The step's only templated input. Fixed here rather than read from a template, so no saved config can
# turn the question or the options into templates that render person or event data as instructions.
AI_DECISION_INPUTS_SCHEMA: list[dict[str, Any]] = [
    {"key": "context", "type": "dictionary", "label": "Context", "required": True, "templating": "hog"}
]


class AIDecisionOptionSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=500, help_text="The answer's name. It labels the step's output for this answer."
    )
    description = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="When this answer applies, in plain words. The model reads it to choose between options.",
    )


class AIDecisionConfigSerializer(serializers.Serializer):
    """The question an AI decision step asks. A workflow save and the decide route validate it alike,
    so a step that saves never fails at run time on its own config."""

    question = serializers.CharField(
        max_length=2000,
        help_text="The question the model answers, in plain words. Never templated: person and event data go in the context.",
    )
    answer_type = serializers.ChoiceField(
        choices=AIDecisionAnswerType.choices,
        help_text="yes_no: the step has a Yes and a No output. pick_one: the step has one output per option.",
    )
    options = serializers.ListField(
        child=AIDecisionOptionSerializer(),
        required=False,
        default=list,
        max_length=MAX_OPTIONS_PER_QUESTION,
        help_text=f"pick_one only: {MIN_OPTIONS} to {MAX_OPTIONS_PER_QUESTION} options with unique names, in output order.",
    )
    yes_means = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="yes_no only: what a yes means, to help the model judge.",
    )
    no_means = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="yes_no only: what a no means, to help the model judge.",
    )
    yes_threshold = serializers.IntegerField(
        min_value=1,
        max_value=99,
        default=50,
        help_text="yes_no only: answer yes when the probability of yes is at or above this percent.",
    )
    unsure_enabled = serializers.BooleanField(
        default=False,
        help_text="Adds an Unsure output after the answer outputs, for answers the model is not sure about.",
    )
    min_pick_probability = serializers.IntegerField(
        min_value=1,
        max_value=99,
        default=60,
        help_text="pick_one with unsure_enabled: answer Unsure when the top option's probability is below this percent.",
    )
    no_threshold = serializers.IntegerField(
        min_value=1,
        max_value=98,
        default=20,
        help_text="yes_no with unsure_enabled: answer no at or below this percent. Must be below yes_threshold.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["answer_type"] == AIDecisionAnswerType.PICK_ONE:
            names = [option["name"] for option in attrs["options"]]
            if len(names) < MIN_OPTIONS:
                raise serializers.ValidationError(
                    {"options": f"Enter between {MIN_OPTIONS} and {MAX_OPTIONS_PER_QUESTION} options."}
                )
            if len(set(names)) != len(names):
                raise serializers.ValidationError({"options": "Give each option a different name."})
        elif attrs["unsure_enabled"] and attrs["no_threshold"] >= attrs["yes_threshold"]:
            raise serializers.ValidationError({"no_threshold": "Set the no threshold below the yes threshold."})
        return attrs


def ai_decision_context_error(inputs: Any) -> str | None:
    context_input = inputs.get("context") if isinstance(inputs, dict) else None
    context = context_input.get("value") if isinstance(context_input, dict) else None
    if not isinstance(context, dict) or not context:
        return "Add at least one field for the model to read."
    if any(not name.strip() or len(name) > MAX_CONTEXT_FIELD_NAME_LENGTH for name in context):
        return f"Give each context field a name of 1 to {MAX_CONTEXT_FIELD_NAME_LENGTH} characters."
    return None
