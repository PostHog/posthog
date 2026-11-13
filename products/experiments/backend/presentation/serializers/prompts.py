"""The input of an experiment that compares versions of an LLM prompt."""

from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.ai_observability.backend.models.llm_prompt import LLMPrompt
from products.experiments.backend.llm_metric_templates import TEMPLATE_NAMES
from products.feature_flags.backend.models.feature_flag import FeatureFlag

CREATE_FROM_PROMPT_MIN_VERSIONS = 2

CREATE_FROM_PROMPT_MAX_VERSIONS = 10


class CreateFromPromptInputSerializer(serializers.Serializer):
    prompt_name = serializers.CharField(
        help_text="The name of the LLM prompt to experiment on. Must already exist for this team.",
    )
    versions = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=CREATE_FROM_PROMPT_MIN_VERSIONS,
        max_length=CREATE_FROM_PROMPT_MAX_VERSIONS,
        help_text=(
            "Ordered list of prompt version numbers to assign to experiment variants. "
            "The first entry is the control variant. Must contain between "
            f"{CREATE_FROM_PROMPT_MIN_VERSIONS} and {CREATE_FROM_PROMPT_MAX_VERSIONS} distinct versions."
        ),
    )
    templates = serializers.ListField(
        child=serializers.ChoiceField(choices=TEMPLATE_NAMES),
        min_length=1,
        max_length=len(TEMPLATE_NAMES),
        help_text=(
            "One or more metric templates to attach as primary metrics. "
            "Each template becomes one metric on the experiment. "
            f"Allowed values: {', '.join(TEMPLATE_NAMES)}."
        ),
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional experiment name. If omitted, a name is generated from the prompt and versions.",
    )
    feature_flag_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional feature flag key. If omitted, a slug is derived from the experiment name.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=3000,
        help_text="Optional experiment description.",
    )

    def validate_versions(self, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValidationError("versions must not contain duplicates.")
        return value

    def validate_templates(self, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValidationError("templates must not contain duplicates.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team = self.context.get("team")
        if team is None:
            raise ValidationError("Team is required in serializer context.")

        prompt_name = attrs["prompt_name"]
        versions = attrs["versions"]

        found = set(
            LLMPrompt.objects.filter(
                team_id=team.id,
                name=prompt_name,
                version__in=versions,
                deleted=False,
            ).values_list("version", flat=True)
        )
        missing = [v for v in versions if v not in found]
        if missing:
            raise ValidationError({"versions": f"Versions not found for prompt {prompt_name!r}: {missing}"})

        # Reusing an existing flag would link the experiment to a flag whose payloads do not
        # encode {prompt_name, prompt_version}, leaving the experiment created but unusable
        # by the SDK (flags.get_flag_payload returns None). Reject explicit collisions so the
        # caller can pick a different key; an omitted key falls through to slug auto-resolution.
        feature_flag_key = attrs.get("feature_flag_key")
        if feature_flag_key and FeatureFlag.objects.filter(team_id=team.id, key=feature_flag_key).exists():
            raise ValidationError(
                {
                    "feature_flag_key": (
                        f"Feature flag {feature_flag_key!r} already exists for this team. "
                        "Pick a different key, or omit this field to auto-generate one."
                    )
                }
            )

        return attrs
