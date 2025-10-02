from django.conf import settings

import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models import User
from posthog.models.team import Team
from posthog.models.utils import uuid7
from posthog.storage import object_storage

from products.feedback.backend.models import (
    FeedbackItem,
    FeedbackItemAssignment,
    FeedbackItemAttachment,
    FeedbackItemCategory,
    FeedbackItemStatus,
    FeedbackItemTopic,
)

logger = structlog.get_logger(__name__)

FIVE_HUNDRED_MEGABYTES = 1024 * 1024 * 500


class FeedbackItemStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackItemStatus
        fields = ["id", "name", "category"]


class FeedbackItemCategorySerializer(serializers.ModelSerializer):
    statuses = FeedbackItemStatusSerializer(many=True, read_only=True)

    class Meta:
        model = FeedbackItemCategory
        fields = ["id", "name", "statuses"]


class FeedbackItemTopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackItemTopic
        fields = ["id", "name"]


class FeedbackItemAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackItemAttachment
        fields = ["id", "storage_ptr", "created_at"]


class FeedbackItemAssignmentSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = FeedbackItemAssignment
        fields = ["user", "role"]


class FeedbackItemSerializer(serializers.ModelSerializer):
    category = FeedbackItemCategorySerializer(read_only=True)
    topic = FeedbackItemTopicSerializer(read_only=True)
    status = FeedbackItemStatusSerializer(read_only=True)
    assignment = FeedbackItemAssignmentSerializer(read_only=True)
    attachments = FeedbackItemAttachmentSerializer(many=True, read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=FeedbackItemCategory.objects.all(), source="category", write_only=True, required=False, allow_null=True
    )
    status_id = serializers.PrimaryKeyRelatedField(
        queryset=FeedbackItemStatus.objects.all(), source="status", write_only=True, required=False, allow_null=True
    )
    assigned_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, required=False, allow_null=True
    )
    topic_id = serializers.PrimaryKeyRelatedField(
        queryset=FeedbackItemTopic.objects.all(), source="topic", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = FeedbackItem
        fields = [
            "id",
            "content",
            "category",
            "category_id",
            "topic",
            "topic_id",
            "status",
            "status_id",
            "assignment",
            "assigned_user_id",
            "attachments",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def update(self, instance, validated_data):
        assigned_user = validated_data.pop("assigned_user_id", None)
        if "assigned_user_id" in self.initial_data:
            if assigned_user is None:
                FeedbackItemAssignment.objects.filter(feedback_item=instance).delete()
            else:
                FeedbackItemAssignment.objects.update_or_create(
                    feedback_item=instance, defaults={"user": assigned_user, "role": None}
                )
        return super().update(instance, validated_data)


class FeedbackItemViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "feedback_item"
    queryset = FeedbackItem.objects.select_related("category", "topic", "status", "assignment__user").prefetch_related(
        "attachments"
    )
    serializer_class = FeedbackItemSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["category", "topic", "status"]

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id)


class FeedbackItemCategoryViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "feedback_item_category"
    queryset = FeedbackItemCategory.objects.prefetch_related("statuses")
    serializer_class = FeedbackItemCategorySerializer

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id)


class FeedbackItemStatusViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "feedback_item_status"
    queryset = FeedbackItemStatus.objects.all()
    serializer_class = FeedbackItemStatusSerializer

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id)


class FeedbackItemTopicViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "feedback_item_topic"
    queryset = FeedbackItemTopic.objects.all()
    serializer_class = FeedbackItemTopicSerializer

    def perform_create(self, serializer):
        serializer.save(team_id=self.team_id)


class PublicFeedbackItemViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "feedback_item"
    authentication_classes = []
    permission_classes = []
    queryset = FeedbackItem.objects.all()
    serializer_class = FeedbackItemSerializer

    def get_team(self):
        token = self.request.GET.get("token")

        if not token:
            raise ValidationError("Missing required token")

        team = Team.objects.get_team_from_cache_or_token(token)
        if not team:
            raise ValidationError("Invalid token")

        return team

    def safely_get_queryset(self, queryset):
        team = self.get_team()
        return queryset.filter(team=team)

    def perform_create(self, serializer):
        team = self.get_team()
        serializer.save(team=team)

    @action(methods=["POST"], detail=False)
    def attach(self, request, **kwargs):
        file_key = generate_feedback_item_attachment_file_key()
        presigned_url = object_storage.get_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, FIVE_HUNDRED_MEGABYTES]],
        )

        return Response({"presigned_url": presigned_url}, status=status.HTTP_201_CREATED)


def generate_feedback_item_attachment_file_key():
    return f"{settings.OBJECT_STORAGE_FEEDBACK_ITEM_ATTACHMENTS_FOLDER}/{str(uuid7())}"


def get_categories_for_remote_config(team: Team) -> list[dict]:
    categories = FeedbackItemCategory.objects.filter(team=team).values("id", "name")
    return list(categories)
