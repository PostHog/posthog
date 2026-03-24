from typing import cast

from django.db.models import Exists, OuterRef, Subquery

from drf_spectacular.utils import extend_schema
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rbac.user_access_control import UserAccessControl

from products.notifications.backend.facade.enums import AC_RESOURCE_TYPES
from products.notifications.backend.models import NotificationEvent, NotificationReadState
from products.notifications.backend.presentation.serializers import NotificationEventSerializer


class NotificationPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class NotificationsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    queryset = NotificationEvent.objects.all()
    serializer_class = NotificationEventSerializer
    scope_object = "INTERNAL"
    posthog_feature_flag = "real-time-notifications"
    permission_classes = [PostHogFeatureFlagPermission]
    pagination_class = NotificationPagination

    def _get_user(self) -> User:
        return cast(User, self.request.user)

    def _get_base_queryset(self):
        user = self._get_user()
        team = self.team
        # Notifications are org-scoped, not team-scoped — a user sees all notifications
        # across projects within their organization.
        return (
            NotificationEvent.objects.filter(
                organization_id=team.organization_id,
                resolved_user_ids__contains=[user.id],
            )
            .annotate(
                read=Exists(
                    NotificationReadState.objects.filter(
                        notification_event_id=OuterRef("id"),
                        user_id=user.id,
                    )
                ),
                read_at=Subquery(
                    NotificationReadState.objects.filter(
                        notification_event_id=OuterRef("id"),
                        user_id=user.id,
                    ).values("created_at")[:1]
                ),
            )
            .order_by("-created_at")
        )

    def _filter_by_access_control(self, queryset):
        resource_types_in_set = set(
            queryset.exclude(resource_type__isnull=True)
            .exclude(resource_type="")
            .values_list("resource_type", flat=True)
            .distinct()
        )

        ac_types_to_check = resource_types_in_set & AC_RESOURCE_TYPES
        if not ac_types_to_check:
            return queryset

        user_ac = UserAccessControl(self._get_user(), self.team)
        if not user_ac.access_controls_supported:
            return queryset

        denied_types = set()
        for resource_type in ac_types_to_check:
            if not user_ac.check_access_level_for_resource(resource_type, "viewer"):
                denied_types.add(resource_type)

        if denied_types:
            queryset = queryset.exclude(resource_type__in=denied_types)

        return queryset

    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self._get_base_queryset()
        queryset = self._filter_by_access_control(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = NotificationEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = NotificationEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def unread_count(self, request: Request, **kwargs) -> Response:
        queryset = self._get_base_queryset()
        queryset = self._filter_by_access_control(queryset)
        count = queryset.filter(read=False).count()
        return Response({"count": count})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=False)
    def mark_all_read(self, request: Request, **kwargs) -> Response:
        user = self._get_user()
        queryset = self._get_base_queryset().filter(read=False)
        event_ids = list(queryset.values_list("id", flat=True))
        if event_ids:
            read_states = [NotificationReadState(notification_event_id=eid, user=user) for eid in event_ids]
            NotificationReadState.objects.bulk_create(read_states, ignore_conflicts=True)
        return Response({"updated": len(event_ids)})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_read")
    def mark_read(self, request: Request, **kwargs) -> Response:
        user = self._get_user()
        event = self.get_object()
        # nosemgrep: idor-lookup-without-team -- event is already authorized via get_object()
        NotificationReadState.objects.get_or_create(notification_event=event, user=user)
        return Response({"status": "ok"})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_unread")
    def mark_unread(self, request: Request, **kwargs) -> Response:
        user = self._get_user()
        event = self.get_object()
        # nosemgrep: idor-lookup-without-team -- event is already authorized via get_object()
        NotificationReadState.objects.filter(notification_event=event, user=user).delete()
        return Response({"status": "ok"})
