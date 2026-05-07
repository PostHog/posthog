from typing import cast

from django.db.models import Exists, OuterRef, QuerySet, Subquery
from django.utils.dateparse import parse_datetime

import posthoganalytics
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.rbac.user_access_control import UserAccessControl

from products.notifications.backend.cache import get_unread_count, invalidate_unread_count, set_unread_count
from products.notifications.backend.facade.enums import AC_RESOURCE_TYPES
from products.notifications.backend.models import NotificationEvent, NotificationReadState
from products.notifications.backend.presentation.serializers import NotificationEventSerializer

_BULK_NOTIFICATION_IDS_SCHEMA = inline_serializer(
    name="BulkNotificationIdsRequest",
    fields={"notification_ids": drf_serializers.ListField(child=drf_serializers.UUIDField())},
)


class NotificationPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class NotificationsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    queryset = NotificationEvent.objects.all()
    serializer_class = NotificationEventSerializer
    scope_object = "INTERNAL"
    pagination_class = NotificationPagination

    def _get_user(self) -> User:
        return cast(User, self.request.user)

    def _is_feature_enabled(self) -> bool:
        user = self._get_user()
        if not user.distinct_id:
            return False
        org_id = str(self.team.organization_id)
        return bool(
            posthoganalytics.feature_enabled(
                "real-time-notifications",
                user.distinct_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )

    def _get_base_queryset(self) -> QuerySet:
        user = self._get_user()
        team = self.team
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

    def _filter_by_access_control(self, queryset: QuerySet) -> QuerySet:
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

    def _apply_filters(self, queryset: QuerySet, request: Request) -> QuerySet:
        params = request.query_params
        for field in ("notification_type", "target_type", "target_id", "resource_type", "resource_id"):
            value = params.get(field)
            if value:
                queryset = queryset.filter(
                    **{field: value}
                )  # nosemgrep: orm-field-injection -- field comes from a fixed tuple
        for field, lookup in (("created_after", "created_at__gte"), ("created_before", "created_at__lt")):
            raw = params.get(field)
            if not raw:
                continue
            # Django decodes "+" timezone offsets in query strings as " "; restore before parsing.
            parsed = parse_datetime(raw.replace(" ", "+"))
            if parsed is None:
                raise ValidationError({field: f"Invalid ISO 8601 timestamp: {raw}"})
            queryset = queryset.filter(
                **{lookup: parsed}
            )  # nosemgrep: orm-field-injection -- lookup comes from a fixed tuple
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="notification_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by notification type",
            ),
            OpenApiParameter(name="target_type", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="target_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="resource_type", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="resource_id", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                name="created_after",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO 8601 timestamp; only events at or after this time",
            ),
            OpenApiParameter(
                name="created_before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO 8601 timestamp; only events strictly before this time",
            ),
        ]
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"results": [], "next": None, "previous": None, "count": 0})

        queryset = self._get_base_queryset()
        queryset = self._apply_filters(queryset, request)
        queryset = self._filter_by_access_control(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = NotificationEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = NotificationEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def unread_count(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"count": 0})

        user = self._get_user()
        org_id = self.team.organization_id
        count = get_unread_count(user.id, org_id)
        if count is None:
            queryset = self._get_base_queryset()
            queryset = self._filter_by_access_control(queryset)
            count = queryset.filter(read=False).count()
            set_unread_count(user.id, org_id, count)
        return Response({"count": count})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=False)
    def mark_all_read(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        queryset = self._get_base_queryset().filter(read=False)
        event_ids = list(queryset.values_list("id", flat=True))
        if event_ids:
            read_states = [NotificationReadState(notification_event_id=eid, user=user) for eid in event_ids]
            NotificationReadState.objects.bulk_create(read_states, ignore_conflicts=True)
        set_unread_count(user.id, self.team.organization_id, 0)
        return Response({"updated": len(event_ids)})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_read")
    def mark_read(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        event = self.get_object()
        # nosemgrep: idor-lookup-without-team -- event is already authorized via get_object()
        NotificationReadState.objects.get_or_create(notification_event=event, user=user)
        invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"status": "ok"})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_unread")
    def mark_unread(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        event = self.get_object()
        # nosemgrep: idor-lookup-without-team -- event is already authorized via get_object()
        NotificationReadState.objects.filter(notification_event=event, user=user).delete()
        invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"status": "ok"})

    @extend_schema(request=_BULK_NOTIFICATION_IDS_SCHEMA)
    @action(methods=["POST"], detail=False, url_path="mark_read_bulk")
    def mark_read_bulk(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"updated": 0})

        user = self._get_user()
        ids = request.data.get("notification_ids", [])
        if not isinstance(ids, list):
            raise ValidationError({"notification_ids": "Expected a list of UUIDs."})
        if not ids:
            return Response({"updated": 0})

        eligible_ids = list(
            NotificationEvent.objects.filter(
                id__in=ids,
                organization_id=self.team.organization_id,
                resolved_user_ids__contains=[user.id],
            ).values_list("id", flat=True)
        )
        if eligible_ids:
            read_states = [NotificationReadState(notification_event_id=eid, user=user) for eid in eligible_ids]
            NotificationReadState.objects.bulk_create(read_states, ignore_conflicts=True)
            invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"updated": len(eligible_ids)})

    @extend_schema(request=_BULK_NOTIFICATION_IDS_SCHEMA)
    @action(methods=["POST"], detail=False, url_path="mark_unread_bulk")
    def mark_unread_bulk(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"updated": 0})

        user = self._get_user()
        ids = request.data.get("notification_ids", [])
        if not isinstance(ids, list):
            raise ValidationError({"notification_ids": "Expected a list of UUIDs."})
        if not ids:
            return Response({"updated": 0})

        eligible_ids = list(
            NotificationEvent.objects.filter(
                id__in=ids,
                organization_id=self.team.organization_id,
                resolved_user_ids__contains=[user.id],
            ).values_list("id", flat=True)
        )
        if eligible_ids:
            NotificationReadState.objects.filter(
                notification_event_id__in=eligible_ids,
                user=user,
            ).delete()
            invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"updated": len(eligible_ids)})
