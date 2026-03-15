from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.db.models import Q, QuerySet

import django_filters
import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Team, User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.llm_analytics.backend.models.score_definitions import ScoreDefinition
from products.llm_analytics.backend.score_definition_configs import ScoreDefinitionConfigField

HUMAN_REVIEWS_FEATURE_FLAG = "llma-trace-review"


def is_human_reviews_feature_enabled(user: User, team: Team) -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)

    return posthoganalytics.feature_enabled(
        HUMAN_REVIEWS_FEATURE_FLAG,
        distinct_id,
        groups={"organization": organization_id, "project": project_id},
        group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


class HumanReviewsFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        return is_human_reviews_feature_enabled(cast(User, request.user), view.team)


class ScoreDefinitionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the scorer.",
    )
    current_version = serializers.IntegerField(
        source="current_version.version",
        read_only=True,
        help_text="Current immutable configuration version number.",
    )
    config = ScoreDefinitionConfigField(
        source="current_version.config",
        read_only=True,
        help_text="Current immutable scorer configuration.",
    )

    class Meta:
        model = ScoreDefinition
        fields = [
            "id",
            "name",
            "description",
            "kind",
            "archived",
            "current_version",
            "config",
            "created_by",
            "created_at",
            "updated_at",
            "team",
        ]
        read_only_fields = fields


class ScoreDefinitionCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable scorer name.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional human-readable description.",
    )
    kind = serializers.ChoiceField(
        choices=ScoreDefinition.Kind.choices,
        help_text="Scorer kind. This cannot be changed after creation.",
    )
    archived = serializers.BooleanField(
        required=False,
        default=False,
        help_text="New scorers are always created as active.",
    )
    config = ScoreDefinitionConfigField(help_text="Initial immutable scorer configuration.")

    def validate_name(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError("`name` is required.")
        return normalized_value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("archived"):
            raise serializers.ValidationError({"archived": "New scorers must be created as active."})
        return attrs


class ScoreDefinitionMetadataSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="Updated scorer name.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Updated scorer description.",
    )
    archived = serializers.BooleanField(
        required=False,
        help_text="Whether the scorer is archived.",
    )

    def validate_name(self, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError("`name` cannot be blank.")
        return normalized_value


class ScoreDefinitionNewVersionSerializer(serializers.Serializer):
    config = ScoreDefinitionConfigField(help_text="Next immutable scorer configuration.")


class ScoreDefinitionFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method="filter_search",
        help_text="Search scorers by name or description.",
    )
    kind = django_filters.ChoiceFilter(
        field_name="kind",
        choices=ScoreDefinition.Kind.choices,
        help_text="Filter by scorer kind.",
    )
    archived = django_filters.BooleanFilter(
        field_name="archived",
        help_text="Filter by archived state.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("kind", "kind"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("current_version__version", "current_version"),
        ),
        help_text="Sort scorers by name, kind, created_at, updated_at, or current_version.",
    )

    class Meta:
        model = ScoreDefinition
        fields = ["kind", "archived"]

    def filter_search(self, queryset: QuerySet, _name: str, value: str) -> QuerySet:
        if value:
            return queryset.filter(Q(name__icontains=value) | Q(description__icontains=value))
        return queryset


@extend_schema(tags=[ProductKey.LLM_ANALYTICS])
class ScoreDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "llm_analytics"
    permission_classes = [HumanReviewsFeatureFlagPermission, AccessControlPermission]
    serializer_class = ScoreDefinitionSerializer
    queryset = ScoreDefinition.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ScoreDefinitionFilter
    http_method_names = ["get", "post", "patch", "head", "options"]

    def safely_get_queryset(
        self, queryset: QuerySet[ScoreDefinition, ScoreDefinition]
    ) -> QuerySet[ScoreDefinition, ScoreDefinition]:
        return (
            queryset.filter(team_id=self.team_id).select_related("current_version", "created_by").order_by("name", "id")
        )

    @transaction.atomic
    def _create_definition(self, validated_data: dict[str, Any]) -> ScoreDefinition:
        definition_data = dict(validated_data)
        config = definition_data.pop("config")
        definition_data.pop("archived", None)
        definition_data["description"] = definition_data.get("description") or ""

        definition = ScoreDefinition.objects.create(
            team=self.team,
            created_by=cast(User, self.request.user),
            **definition_data,
        )
        definition.create_new_version(config=config, created_by=cast(User, self.request.user))
        return definition

    def _update_definition_metadata(
        self, definition: ScoreDefinition, validated_data: dict[str, Any]
    ) -> ScoreDefinition:
        definition_data = dict(validated_data)

        if "description" in definition_data:
            definition_data["description"] = definition_data["description"] or ""

        for field, value in definition_data.items():
            setattr(definition, field, value)

        if definition_data:
            definition.save(update_fields=[*definition_data.keys(), "updated_at"])

        return definition

    def _create_definition_version(
        self, definition: ScoreDefinition, validated_data: dict[str, Any]
    ) -> ScoreDefinition:
        definition.create_new_version(config=validated_data["config"], created_by=cast(User, self.request.user))
        definition.refresh_from_db(fields=["current_version", "updated_at"])
        return definition

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search scorers by name or description.",
                examples=[OpenApiExample("Search scorer", value="quality")],
            ),
            OpenApiParameter(
                "kind",
                OpenApiTypes.STR,
                description="Filter by scorer kind.",
                examples=[OpenApiExample("Categorical scorer", value="categorical")],
            ),
            OpenApiParameter(
                "archived",
                OpenApiTypes.BOOL,
                description="Filter by archived state.",
                examples=[OpenApiExample("Active scorers", value=False)],
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                description="Sort by name, kind, created_at, updated_at, or current_version.",
                examples=[OpenApiExample("Sort by name", value="name")],
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @validated_request(
        request_serializer=ScoreDefinitionCreateSerializer,
        responses={201: OpenApiResponse(response=ScoreDefinitionSerializer)},
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        definition = self._create_definition(dict(request.validated_data))
        return Response(self.get_serializer(definition).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=ScoreDefinitionMetadataSerializer,
        responses={200: OpenApiResponse(response=ScoreDefinitionSerializer)},
    )
    def partial_update(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        definition = self.get_object()
        self._update_definition_metadata(definition, dict(request.validated_data))
        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)

    @extend_schema(request=ScoreDefinitionNewVersionSerializer, responses=ScoreDefinitionSerializer)
    @action(detail=True, methods=["post"], url_path="new_version")
    def new_version(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        definition = self.get_object()
        serializer = ScoreDefinitionNewVersionSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "score_definition_kind": definition.kind},
        )
        serializer.is_valid(raise_exception=True)
        self._create_definition_version(definition, dict(serializer.validated_data))
        return Response(self.get_serializer(definition).data, status=status.HTTP_200_OK)
