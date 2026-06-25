from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action

from products.logs.backend.models import LogsUserConfig

# Bound on how many facets a user can pin, so the rail config can't grow without limit.
MAX_CUSTOM_FACETS = 50


class CustomFacetListSerializer(serializers.ListSerializer):
    def validate(self, attrs: list[dict]) -> list[dict]:
        if len(attrs) > MAX_CUSTOM_FACETS:
            raise serializers.ValidationError(f"At most {MAX_CUSTOM_FACETS} custom facets are allowed.")
        seen: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for facet in attrs:
            ident = (facet["key"], facet["attribute_type"])
            if ident not in seen:
                seen.add(ident)
                deduped.append(facet)
        return deduped


class CustomFacetSerializer(serializers.Serializer):
    key = serializers.CharField(
        max_length=200,
        help_text="Attribute key to facet on, e.g. 'k8s.namespace.name' or 'http.status_code'.",
    )
    attribute_type = serializers.ChoiceField(
        choices=["log", "resource"],
        help_text='Where the key lives: "resource" for resource attributes, "log" for log attributes.',
    )

    class Meta:
        list_serializer_class = CustomFacetListSerializer


class LogsCustomFacetsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The requesting user's custom facets for the current project — the facets they pinned into the
    rail's Custom group. Stored as a single (team, user) row; the whole set is replaced on write."""

    scope_object = "logs"
    serializer_class = CustomFacetSerializer

    @extend_schema(responses=CustomFacetSerializer(many=True))
    def list(self, request: Request, *args, **kwargs) -> Response:
        # Auto-scoped to the canonical team by TeamScopedManager; only the user filter is ours to add.
        config = LogsUserConfig.objects.filter(user=request.user).first()
        facets = config.custom_facets if config else []
        # Serialize on the way out so the response honors the declared schema and can't drift from
        # create if CustomFacetSerializer ever grows a to_representation override or computed field.
        return Response(CustomFacetSerializer(facets, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(request=CustomFacetSerializer(many=True), responses=CustomFacetSerializer(many=True))
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomFacetSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        custom_facets = serializer.validated_data
        # team is passed explicitly: the manager's read scope doesn't propagate into row creation.
        LogsUserConfig.objects.update_or_create(
            user=request.user,
            defaults={"custom_facets": custom_facets, "team": self.team},
        )
        report_user_action(
            request.user,
            "logs custom facets updated",
            {"count": len(custom_facets)},
            team=self.team,
            request=request,
        )
        # serializer.data is to_representation(validated_data) — same serializer path as list, so the
        # two endpoints return an identical shape (and reflect the dedup applied during validation).
        return Response(serializer.data, status=status.HTTP_200_OK)
