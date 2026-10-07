from collections.abc import Mapping
from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.feature_flags.backend.facade.config import detect_config_format, parse_v2_config
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class FlagValueQuerySerializer(serializers.Serializer):
    key = serializers.CharField(required=False, help_text="The flag ID", allow_blank=True)


class FlagValueItemSerializer(serializers.Serializer):
    name = serializers.JSONField()


class FlagValueResponseSerializer(serializers.Serializer):
    results = FlagValueItemSerializer(many=True)
    refreshing = serializers.BooleanField()


class FlagValueViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoint for getting possible values for feature flags.
    Returns true/false for every flag, plus the variant keys of a multivariate flag or the
    string values of a config version 2 string flag.
    """

    permission_classes = [IsAuthenticated]
    scope_object = "feature_flag"

    @validated_request(
        query_serializer=FlagValueQuerySerializer,
        responses={
            200: OpenApiResponse(response=FlagValueResponseSerializer),
            400: OpenApiResponse(description="Bad request"),
            404: OpenApiResponse(description="Not found"),
        },
    )
    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def values(self, request: request.Request, **kwargs) -> response.Response:
        """
        Get possible values for a feature flag.

        Query parameters:
        - key: The flag ID (required)
        Returns:

        - Array of objects with 'name' field containing possible values
        """
        flag_id = request.validated_query_data.get("key")

        if not flag_id:
            return response.Response({"error": "Missing flag ID parameter"}, status=400)

        try:
            flag_id_int = int(flag_id)
        except (ValueError, TypeError):
            return response.Response({"error": "Invalid flag ID - must be a valid integer"}, status=400)

        try:
            flag = FeatureFlag.objects.get(team=self.team, id=flag_id_int)
        except FeatureFlag.DoesNotExist:
            return response.Response({"error": "Feature flag not found"}, status=404)

        # values is detail=False, so DRF never routes through get_object() and its
        # built-in check_object_permissions call. Call it explicitly here.
        # Otherwise a caller bypasses a flag's per-flag "none" access by naming its ID directly.
        self.check_object_permissions(request, flag)

        # Always include true and false for any flag; a flag dependency on true matches any enabled value
        values: list[dict[str, bool | str]] = [{"name": True}, {"name": False}]

        config_format = detect_config_format(flag.filters).kind
        if config_format == "v1":
            # Add variant keys if this is a multivariate flag
            if flag.filters.get("multivariate") and flag.filters["multivariate"].get("variants"):
                for variant in flag.filters["multivariate"]["variants"]:
                    variant_key = variant.get("key")
                    if variant_key:
                        values.append({"name": variant_key})
        elif config_format == "v2":
            values.extend({"name": value} for value in _v2_string_values(flag.filters))

        return response.Response({"results": values, "refreshing": False})


def _v2_string_values(filters: Mapping[str, Any]) -> list[str]:
    """The strings a v2 string flag serves as its value, in rule order and then the default.

    Other return types serve only true or false as the flag value, and an undecodable document
    lists nothing beyond those.
    """
    try:
        config = parse_v2_config(filters)
    except (KeyError, TypeError, ValueError):
        return []
    if config.return_type != "string":
        return []
    candidates = [
        *(value for rule in config.rules for value in (rule.value, *rule.variant_values)),
        config.default_value,
    ]
    return list(dict.fromkeys(value for value in candidates if isinstance(value, str)))
