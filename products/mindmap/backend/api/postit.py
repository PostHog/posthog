from typing import Any, cast

from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team import Team

from products.mindmap.backend import service
from products.mindmap.backend.models import MindMapPostIt


class MindMapPostItSerializer(serializers.ModelSerializer):
    short_id = serializers.CharField(read_only=True, help_text="Unique short id used as the post-it's API key")
    title = serializers.CharField(max_length=256, help_text="Short title shown on the post-it")
    body = serializers.CharField(required=False, allow_blank=True, help_text="Longer optional body text")
    color = serializers.ChoiceField(
        choices=MindMapPostIt.Color.choices, required=False, help_text="Sticky-note background color"
    )
    emoji = serializers.CharField(required=False, allow_blank=True, max_length=8, help_text="Optional single emoji")
    position_x = serializers.FloatField(required=False, help_text="X coordinate on the canvas")
    position_y = serializers.FloatField(required=False, help_text="Y coordinate on the canvas")
    notebook_short_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=12,
        help_text="Notebook short_id this post-it links to (clicking opens it)",
    )

    class Meta:
        model = MindMapPostIt
        fields = [
            "short_id",
            "title",
            "body",
            "color",
            "emoji",
            "position_x",
            "position_y",
            "notebook_short_id",
            "created_at",
            "last_modified_at",
        ]
        read_only_fields = ["created_at", "last_modified_at"]

    def create(self, validated_data: dict[str, Any]) -> MindMapPostIt:
        team = cast(Team, self.context["get_team"]())
        user = self.context["request"].user
        return service.create_postit(team=team, user=user, **validated_data)

    def update(self, instance: MindMapPostIt, validated_data: dict[str, Any]) -> MindMapPostIt:
        team = cast(Team, self.context["get_team"]())
        user = self.context["request"].user
        return service.update_postit(team=team, user=user, short_id=instance.short_id, **validated_data)


class _BulkPositionItemSerializer(serializers.Serializer):
    short_id = serializers.CharField(max_length=12, help_text="Post-it short_id")
    position_x = serializers.FloatField(help_text="New X coordinate")
    position_y = serializers.FloatField(help_text="New Y coordinate")


class _BulkPositionRequestSerializer(serializers.Serializer):
    updates = _BulkPositionItemSerializer(many=True)


class _BulkPositionResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField(help_text="Number of post-its actually updated")


class MindMapPostItViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "mindmap"
    serializer_class = MindMapPostItSerializer
    queryset = MindMapPostIt.objects.all()
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: QuerySet[MindMapPostIt]) -> QuerySet[MindMapPostIt]:
        return queryset.filter(deleted=False).order_by("created_at")

    @extend_schema(responses={204: OpenApiResponse(description="Post-it soft-deleted")})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance: MindMapPostIt = self.get_object()
        service.delete_postit(team=self.team, user=request.user, short_id=instance.short_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=_BulkPositionRequestSerializer,
        responses={200: _BulkPositionResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="bulk_position")
    def bulk_position(self, request: Request, **kwargs: Any) -> Response:
        payload = _BulkPositionRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updated = service.bulk_position(
            team=self.team,
            user=request.user,
            updates=payload.validated_data["updates"],
        )
        return Response({"updated": updated})
