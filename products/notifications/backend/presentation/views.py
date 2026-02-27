from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.permissions import PostHogFeatureFlagPermission

from products.notifications.backend.models import Notification
from products.notifications.backend.presentation.serializers import NotificationSerializer


class NotificationsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    scope_object = "INTERNAL"
    posthog_feature_flag = "real-time-notifications"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(recipient=self.request.user).select_related("actor")

    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset[:50], many=True)
        return Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def unread_count(self, request: Request, **kwargs) -> Response:
        count = self.get_queryset().filter(read=False).count()
        return Response({"count": count})

    @action(methods=["POST"], detail=False)
    def mark_all_read(self, request: Request, **kwargs) -> Response:
        now = timezone.now()
        updated = self.get_queryset().filter(read=False).update(read=True, read_at=now)
        return Response({"updated": updated})

    @action(methods=["POST"], detail=True, url_path="mark_read")
    def mark_read(self, request: Request, **kwargs) -> Response:
        notification = self.get_object()
        if not notification.read:
            notification.read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["read", "read_at"])
        return Response(NotificationSerializer(notification).data)
