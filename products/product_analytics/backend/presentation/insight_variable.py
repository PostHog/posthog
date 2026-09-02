import json

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication

from products.product_analytics.backend.facade.models import InsightVariable


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

        fields = [
            "id",
            "name",
            "type",
            "default_value",
            "created_by",
            "created_at",
            "code_name",
            "values",
            "is_multi",
            "values_query",
            "values_query_connection_id",
        ]

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
            "is_multi": {"help_text": "Whether a List variable accepts multiple selected values."},
            "values_query": {
                "help_text": "HogQL query whose first result column supplies the allowed values for a List variable. An optional second column supplies display labels."
            },
            "values_query_connection_id": {
                "help_text": "ID of the external data source connection values_query runs against. Null runs it against PostHog."
            },
        }

    def validate(self, attrs):
        variable_type = attrs.get("type", getattr(self.instance, "type", None))
        if variable_type == InsightVariable.Type.LIST:
            is_multi = attrs.get("is_multi", getattr(self.instance, "is_multi", False))
            if "is_multi" in attrs and "default_value" not in attrs and self.instance is not None:
                attrs["default_value"] = self.instance.default_value
            elif is_multi and "default_value" not in attrs and self.instance is None:
                attrs["default_value"] = []
            # Only validate `values` when the payload provides it — instance data may hold
            # legacy shapes that shouldn't block unrelated updates (reads normalize them).
            if "values" in attrs:
                values = attrs["values"]
                attrs["values"] = self._coerce_list_values(values) if isinstance(values, list) else []
            # A blank query means "not query-backed" — store null so the UI falls back to static options.
            if isinstance(attrs.get("values_query"), str) and not attrs["values_query"].strip():
                attrs["values_query"] = None
            effective_values_query = (
                attrs["values_query"] if "values_query" in attrs else getattr(self.instance, "values_query", None)
            )
            if effective_values_query is None:
                attrs["values_query_connection_id"] = None
            if "default_value" in attrs:
                default_value = attrs["default_value"]
                if is_multi:
                    raw_default_values = default_value if isinstance(default_value, list) else [default_value]
                    attrs["default_value"] = [
                        value
                        for raw_value in raw_default_values
                        if (value := _coerce_list_value_lenient(raw_value)) is not None
                    ]
                elif isinstance(default_value, list):
                    attrs["default_value"] = _coerce_list_value_lenient(default_value[0]) if default_value else ""
                else:
                    attrs["default_value"] = _coerce_list_value_lenient(default_value) or ""
        else:
            attrs["is_multi"] = False
            attrs["values_query"] = None
            attrs["values_query_connection_id"] = None

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
            raw_default_value = data.get("default_value")
            if instance.is_multi:
                raw_default_values = raw_default_value if isinstance(raw_default_value, list) else [raw_default_value]
                data["default_value"] = [
                    value
                    for raw_value in raw_default_values
                    if (value := _coerce_list_value_lenient(raw_value)) is not None
                ]
            else:
                data["default_value"] = _coerce_list_value_lenient(raw_default_value)
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
