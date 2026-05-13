from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team import Team

from products.mindmap.backend import service
from products.mindmap.backend.models import MindMapEdge


class MindMapEdgeSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Edge UUID")
    source = serializers.CharField(max_length=12, help_text="Source post-it short_id")
    target = serializers.CharField(max_length=12, help_text="Target post-it short_id")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the edge was created")

    def create(self, validated_data: dict[str, Any]) -> MindMapEdge:
        team = cast(Team, self.context["get_team"]())
        user = self.context["request"].user
        return service.connect(
            team=team,
            user=user,
            source_short_id=validated_data["source"],
            target_short_id=validated_data["target"],
        )

    def to_representation(self, instance: MindMapEdge) -> dict[str, Any]:
        return {
            "id": str(instance.id),
            "source": instance.source.short_id,
            "target": instance.target.short_id,
            "created_at": instance.created_at,
        }


class MindMapEdgeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "mindmap"
    serializer_class = MindMapEdgeSerializer
    queryset = MindMapEdge.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[MindMapEdge]) -> QuerySet[MindMapEdge]:
        return queryset.select_related("source", "target").order_by("created_at")

    @extend_schema(responses={200: MindMapEdgeSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(request=MindMapEdgeSerializer, responses={201: MindMapEdgeSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = serializer.save()
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={204: OpenApiResponse(description="Edge deleted")},
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = request.query_params.get("source")
        target = request.query_params.get("target")
        if not source or not target:
            return Response(
                {"detail": "Both 'source' and 'target' query params are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service.disconnect(team=self.team, user=request.user, source_short_id=source, target_short_id=target)
        return Response(status=status.HTTP_204_NO_CONTENT)
