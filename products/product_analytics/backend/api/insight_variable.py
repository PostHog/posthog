import json

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication

from products.product_analytics.backend.models.insight_variable import InsightVariable


def _scalar_to_str(value: object) -> str | None:
    """Coerce a scalar to its string form, or None if it isn't a scalar."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # bool before int/float: bool is an int subclass, and the UI uses lowercase
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return None


def _coerce_list_value_lenient(value: object) -> str | None:
    """Mirror the frontend's read-side coercion: option-shaped objects use their
    value/label, scalars stringify, null drops, anything else renders as JSON. Never
    raises — used on read so legacy rows round-trip cleanly instead of failing a later
    write against the stricter validation."""
    if value is None:
        return None
    scalar = _scalar_to_str(value)
    if scalar is not None:
        return scalar
    if isinstance(value, dict):
        for key in ("value", "label"):
            inner = _scalar_to_str(value.get(key))
            if inner is not None:
                return inner
    return json.dumps(value)


class InsightVariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightVariable

        fields = ["id", "name", "type", "default_value", "created_by", "created_at", "code_name", "values"]

        read_only_fields = ["id", "code_name", "created_by", "created_at"]
        extra_kwargs = {
            "id": {"help_text": "UUID of the SQL variable."},
            "name": {"help_text": "Human-readable name for the SQL variable."},
            "type": {"help_text": "Variable type. Controls how the value is rendered and substituted in HogQL."},
            "default_value": {"help_text": "Default value used when a query references this variable."},
            "created_by": {"help_text": "ID of the user who created the SQL variable."},
            "created_at": {"help_text": "Timestamp when the SQL variable was created."},
            "code_name": {
                "help_text": "Generated code-safe name used in HogQL as {variables.code_name}. Derived from name."
            },
            "values": {"help_text": "Allowed values for List variables. Null for other variable types."},
        }

    def validate(self, attrs):
        variable_type = attrs.get("type", getattr(self.instance, "type", None))
        if variable_type == InsightVariable.Type.LIST:
            # Only validate `values` when the payload provides it — instance data may hold
            # legacy shapes that shouldn't block unrelated updates (reads normalize them).
            if "values" in attrs:
                values = attrs["values"]
                attrs["values"] = self._coerce_list_values(values) if isinstance(values, list) else []
            # `default_value` is a single option; coerce leniently so a legacy shape or a
            # round-tripped read can't be stored as non-string (the UI treats it as text).
            if "default_value" in attrs:
                attrs["default_value"] = _coerce_list_value_lenient(attrs["default_value"]) or ""

        return attrs

    def _coerce_list_values(self, values: list) -> list[str]:
        coerced: list[str] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            scalar = _scalar_to_str(value)
            if scalar is None:
                shape = "an object" if isinstance(value, dict) else "an array"
                raise ValidationError(
                    {
                        "values": f"List variable values must be strings or numbers (got {shape} at index {index}). Enter each value as plain text or a number."
                    }
                )
            coerced.append(scalar)
        return coerced

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # `values` is a JSONField; older List records may hold null, a non-array value, or
        # non-string elements (e.g. option-shaped objects). Normalize on read so clients
        # always get a clean string array — and so writing this data back round-trips
        # instead of tripping the stricter write validation.
        if instance.type == InsightVariable.Type.LIST:
            raw_values = data.get("values")
            data["values"] = (
                [coerced for value in raw_values if (coerced := _coerce_list_value_lenient(value)) is not None]
                if isinstance(raw_values, list)
                else []
            )
            data["default_value"] = _coerce_list_value_lenient(data.get("default_value"))
        return data

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        validated_data["code_name"] = (
            "".join(c for c in validated_data["name"] if c.isalnum() or c == " " or c == "_").replace(" ", "_").lower()
        )

        if InsightVariable.objects.filter(
            team_id=validated_data["team_id"], code_name=validated_data["code_name"]
        ).exists():
            raise ValidationError("Variable with this code name already exists")

        return InsightVariable.objects.create(**validated_data)


class InsightVariablePagination(pagination.PageNumberPagination):
    page_size = 500


@extend_schema(extensions={"x-product": ProductKey.DATA_WAREHOUSE})
class InsightVariableViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "insight_variable"
    queryset = InsightVariable.objects.all()
    pagination_class = InsightVariablePagination
    serializer_class = InsightVariableSerializer
    filter_backends = [DjangoFilterBackend]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        if isinstance(
            request.successful_authenticator,
            SharingAccessTokenAuthentication | SharingPasswordProtectedAuthentication,
        ):
            raise PermissionDenied("Insight variables cannot be accessed via sharing authentication")


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariable]) -> dict:
    # Keep the variables in an insight up to date based on variable code names that exist
    current_variables = stale_variables
    insight_variables = latest_variables
    final_variables = {}

    # Create a lookup for insight variables by code_name for quick access
    insight_variables_by_code_name = {var.code_name: var for var in insight_variables}

    # For each variable in current_variables, update with data from insight_variables if code_name matches
    for _, v in current_variables.items():
        code_name = v.get("code_name")
        if code_name in insight_variables_by_code_name:
            # Update the variable with corresponding data from insight_variables
            matched_var = insight_variables_by_code_name[code_name]
            # Add attributes from matched_var that can be serialized to JSON
            final_variables[str(matched_var.id)] = {
                **v,
                "code_name": matched_var.code_name,
                "variableId": str(matched_var.id),
            }

    return final_variables
