import re
from typing import Any

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

SCORE_DEFINITION_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")


def normalize_score_definition_key(value: str, *, field_name: str = "key") -> str:
    normalized_value = value.strip().lower()

    if not normalized_value:
        raise serializers.ValidationError(f"`{field_name}` is required.")

    if not SCORE_DEFINITION_KEY_PATTERN.fullmatch(normalized_value):
        raise serializers.ValidationError(
            f"`{field_name}` must use lowercase letters, numbers, underscores, or hyphens."
        )

    return normalized_value


class CategoricalScoreOptionSerializer(serializers.Serializer):
    key = serializers.CharField(
        max_length=128,
        help_text="Stable option key. Use lowercase letters, numbers, underscores, or hyphens.",
    )
    label = serializers.CharField(max_length=256, help_text="Human-readable option label.")  # type: ignore[assignment]

    def validate_key(self, value: str) -> str:
        return normalize_score_definition_key(value, field_name="key")


class CategoricalScoreDefinitionConfigSerializer(serializers.Serializer):
    options = CategoricalScoreOptionSerializer(
        many=True,
        help_text="Ordered categorical options available to the scorer.",
    )
    selection_mode = serializers.ChoiceField(
        required=False,
        choices=[("single", "single"), ("multiple", "multiple")],
        help_text="Whether reviewers can select one option or multiple options. Defaults to `single`.",
    )
    min_selections = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Optional minimum number of options that can be selected when `selection_mode` is `multiple`.",
    )
    max_selections = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Optional maximum number of options that can be selected when `selection_mode` is `multiple`.",
    )

    def validate_options(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(value) == 0:
            raise serializers.ValidationError("Provide at least one categorical option.")

        option_keys = [option["key"] for option in value]
        if len(option_keys) != len(set(option_keys)):
            raise serializers.ValidationError("Categorical option keys must be unique.")

        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        selection_mode = attrs.get("selection_mode") or "single"
        minimum = attrs.get("min_selections")
        maximum = attrs.get("max_selections")
        option_count = len(attrs.get("options", []))

        if selection_mode == "single":
            if minimum is not None:
                raise serializers.ValidationError(
                    {"min_selections": "`min_selections` is only supported when `selection_mode` is `multiple`."}
                )
            if maximum is not None:
                raise serializers.ValidationError(
                    {"max_selections": "`max_selections` is only supported when `selection_mode` is `multiple`."}
                )
            return attrs

        if minimum is not None and minimum > option_count:
            raise serializers.ValidationError(
                {"min_selections": "Ensure `min_selections` is less than or equal to the number of options."}
            )

        if maximum is not None and maximum > option_count:
            raise serializers.ValidationError(
                {"max_selections": "Ensure `max_selections` is less than or equal to the number of options."}
            )

        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError(
                {"max_selections": "Ensure `max_selections` is greater than or equal to `min_selections`."}
            )

        return attrs


class NumericScoreDefinitionConfigSerializer(serializers.Serializer):
    min = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Optional inclusive minimum score.",
    )
    max = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Optional inclusive maximum score.",
    )
    step = serializers.FloatField(
        required=False,
        allow_null=True,
        help_text="Optional increment step for numeric input, for example 1 or 0.5.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        minimum = attrs.get("min")
        maximum = attrs.get("max")
        step = attrs.get("step")

        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError({"max": "Ensure `max` is greater than or equal to `min`."})

        if step is not None and step <= 0:
            raise serializers.ValidationError({"step": "Ensure `step` is greater than 0."})

        return attrs


class BooleanScoreDefinitionConfigSerializer(serializers.Serializer):
    true_label = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional label for a true value.",
    )
    false_label = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional label for a false value.",
    )


SCORE_DEFINITION_CONFIG_SCHEMA = PolymorphicProxySerializer(
    component_name="ScoreDefinitionConfig",
    serializers=[
        CategoricalScoreDefinitionConfigSerializer,
        NumericScoreDefinitionConfigSerializer,
        BooleanScoreDefinitionConfigSerializer,
    ],
    resource_type_field_name=None,
)


def build_score_definition_config_serializer(kind: str, *args: Any, **kwargs: Any) -> serializers.Serializer:
    if kind == "categorical":
        return CategoricalScoreDefinitionConfigSerializer(*args, **kwargs)
    if kind == "numeric":
        return NumericScoreDefinitionConfigSerializer(*args, **kwargs)
    if kind == "boolean":
        return BooleanScoreDefinitionConfigSerializer(*args, **kwargs)

    raise serializers.ValidationError({"kind": "Unsupported score definition kind."})


@extend_schema_field(SCORE_DEFINITION_CONFIG_SCHEMA)
class ScoreDefinitionConfigField(serializers.Field):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        kind = self._get_score_definition_kind()
        serializer = build_score_definition_config_serializer(kind, data=data)
        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)

    def to_representation(self, value: Any) -> Any:
        return value

    def _get_score_definition_kind(self) -> str:
        initial_data = getattr(self.parent, "initial_data", None)
        if isinstance(initial_data, dict):
            kind = initial_data.get("kind")
            if isinstance(kind, str) and kind:
                return kind

        instance = getattr(self.parent, "instance", None)
        if instance is not None and hasattr(instance, "kind"):
            kind = instance.kind
            if isinstance(kind, str) and kind:
                return kind

        kind = self.context.get("score_definition_kind")
        if isinstance(kind, str) and kind:
            return kind

        raise serializers.ValidationError({"kind": "Set `kind` before validating `config`."})
