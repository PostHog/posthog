import structlog
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.feedback.backend.models import FeedbackItem

logger = structlog.get_logger(__name__)


class FeedbackItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackItem
        fields = ["id", "content"]
        read_only_fields = ["id", "content"]


class FeedbackItemViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "feedback_item"
    queryset = FeedbackItem.objects.all()
    serializer_class = FeedbackItemSerializer
