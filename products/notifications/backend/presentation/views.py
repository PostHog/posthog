from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES, visible_teams_for_user
from products.notifications.backend.cache import (
    UnreadSummary,
    get_unread_summary,
    invalidate_unread_count,
    set_unread_summary,
)
from products.notifications.backend.facade.enums import Priority, TargetType
from products.notifications.backend.models import NotificationArchiveState, NotificationEvent, NotificationReadState
from products.notifications.backend.presentation.serializers import (
    CURSOR_SEPARATOR,
    ArchiveAllResponseSerializer,
    BulkNotificationIdsRequestSerializer,
    BulkUnarchiveRequestSerializer,
    NotificationEventSerializer,
    NotificationFiltersQuerySerializer,
    NotificationListQuerySerializer,
    UnarchiveRequestSerializer,
    UnreadSummarySerializer,
    UpdatedCountSerializer,
)

DIRECT_TARGET_TYPES = (TargetType.USER.value, TargetType.ROLE.value)
EMPTY_UNREAD_SUMMARY: UnreadSummary = {"count": 0, "direct_count": 0, "has_critical": False}


class NotificationPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100

    def get_paginated_response(self, data: Any) -> Response:
        response = super().get_paginated_response(data)
        response.data["next_cursor"] = self._next_cursor(data)
        return response

    def _next_cursor(self, data: Any) -> str | None:
        if not data or self.limit is None or len(data) < self.limit:
            return None
        last = data[-1]
        return f"{last['created_at']}{CURSOR_SEPARATOR}{last['id']}"

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        paginated = super().get_paginated_response_schema(schema)
        paginated["properties"]["next_cursor"] = {
            "type": "string",
            "nullable": True,
            "description": "Pass as `before` to get the next page. Null on the last page.",
        }
        return paginated


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
        visible_team_ids = visible_teams_for_user(
            team.organization, self.user_access_control, self.user_permissions
        ).values("id")
        return (
            NotificationEvent.objects.filter(
                Q(team__isnull=True) | Q(team_id__in=visible_team_ids),
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
                archived=Exists(
                    NotificationArchiveState.objects.filter(
                        notification_event_id=OuterRef("id"),
                        user_id=user.id,
                    )
                ),
            )
            .order_by("-created_at", "-id")
        )

    def _filter_by_access_control(self, queryset: QuerySet) -> QuerySet:
        resource_types_by_team: dict[int, set[APIScopeObject]] = defaultdict(set)
        for team_id, resource_type in (
            queryset.filter(resource_type__in=ACCESS_CONTROL_RESOURCES)
            .order_by()
            .values_list("team_id", "resource_type")
            .distinct()
        ):
            resource_types_by_team[team_id or self.team.id].add(cast(APIScopeObject, resource_type))
        if not resource_types_by_team:
            return queryset

        access_by_team = self.user_access_control.for_team_ids(resource_types_by_team.keys())
        denied = Q()
        for team_id, resource_types in resource_types_by_team.items():
            access = access_by_team.get(team_id)
            if access is None or not access.access_controls_supported:
                continue
            denied_types = [
                resource_type
                for resource_type in resource_types
                if not access.check_access_level_for_resource(resource_type, "viewer")
            ]
            if not denied_types:
                continue
            same_project = Q(team__isnull=True) if team_id == self.team.id else Q()
            denied |= (Q(team_id=team_id) | same_project) & Q(resource_type__in=denied_types)
        return queryset.exclude(denied) if denied else queryset

    def _apply_filters(self, queryset: QuerySet, filters: Mapping[str, Any]) -> QuerySet:
        # Explicit per-field filters (no dict-unpack) so semgrep's no-request-param-orm-filter
        # taint analysis is satisfied — every field name is hard-coded at the call site.
        if value := filters.get("notification_type"):
            queryset = queryset.filter(notification_type__in=value)
        if value := filters.get("target_type"):
            queryset = queryset.filter(target_type__in=value)
        if value := filters.get("target_id"):
            queryset = queryset.filter(target_id=value)
        if value := filters.get("resource_type"):
            queryset = queryset.filter(resource_type=value)
        if value := filters.get("resource_id"):
            queryset = queryset.filter(resource_id=value)
        if (value := filters.get("team_id")) is not None:
            queryset = queryset.filter(Q(team_id=value) | Q(team__isnull=True))
        if value := filters.get("priority"):
            queryset = queryset.filter(priority=value)
        if (value := filters.get("read")) is not None:
            queryset = queryset.filter(read=value)
        if value := filters.get("created_after"):
            queryset = queryset.filter(created_at__gte=value)
        if value := filters.get("created_before"):
            queryset = queryset.filter(created_at__lt=value)
        return queryset

    def _matching_events(self, filters: Mapping[str, Any], **base_filters: bool) -> QuerySet:
        queryset = self._get_base_queryset().filter(**base_filters)
        queryset = self._apply_filters(queryset, filters)
        return self._filter_by_access_control(queryset)

    @extend_schema(parameters=[NotificationListQuerySerializer])
    def list(self, request: Request, *args, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"results": [], "next": None, "previous": None, "count": 0, "next_cursor": None})

        query = NotificationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        queryset = self._matching_events(filters, archived=filters["archived"])
        if before := filters.get("before"):
            created_at, event_id = before
            queryset = queryset.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=event_id))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = NotificationEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = NotificationEventSerializer(queryset, many=True)
        return Response(serializer.data)

    @validated_request(responses={200: OpenApiResponse(response=NotificationEventSerializer)})
    def retrieve(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        if not self._is_feature_enabled():
            raise Http404
        queryset = self._filter_by_access_control(self._get_base_queryset())
        event = get_object_or_404(queryset, pk=self.kwargs["pk"])  # nosemgrep: idor-taint-user-input-to-model-get
        return Response(NotificationEventSerializer(event).data)

    @validated_request(responses={200: OpenApiResponse(response=UnreadSummarySerializer)})
    @action(methods=["GET"], detail=False)
    def unread_count(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response(EMPTY_UNREAD_SUMMARY)

        user = self._get_user()
        org_id = self.team.organization_id
        summary = get_unread_summary(user.id, org_id)
        if summary is None:
            queryset = self._filter_by_access_control(self._get_base_queryset().filter(archived=False))
            counts = queryset.filter(read=False).aggregate(
                count=Count("id"),
                direct_count=Count("id", filter=Q(target_type__in=DIRECT_TARGET_TYPES)),
                critical_count=Count("id", filter=Q(priority=Priority.CRITICAL.value)),
            )
            summary = {
                "count": counts["count"],
                "direct_count": counts["direct_count"],
                "has_critical": counts["critical_count"] > 0,
            }
            set_unread_summary(user.id, org_id, summary)
        return Response(summary)

    @validated_request(
        query_serializer=NotificationFiltersQuerySerializer,
        responses={200: OpenApiResponse(response=UpdatedCountSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def mark_all_read(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response(UpdatedCountSerializer({"updated": 0}).data)

        user = self._get_user()
        event_ids = list(
            self._matching_events(request.validated_query_data, read=False, archived=False).values_list("id", flat=True)
        )
        if event_ids:
            read_states = [NotificationReadState(notification_event_id=eid, user=user) for eid in event_ids]
            NotificationReadState.objects.bulk_create(read_states, ignore_conflicts=True)
        invalidate_unread_count(user.id, self.team.organization_id)
        return Response(UpdatedCountSerializer({"updated": len(event_ids)}).data)

    def _get_recipient_event_or_404(self) -> NotificationEvent:
        # NotificationEvent is org-scoped + user-targeted, not team-scoped. self.get_object() applies
        # the team_id URL filter from TeamAndOrgViewSetMixin and 404s on org-level notifications
        # (team_id=NULL). (organization_id, resolved_user_ids__contains=[user.id]) is the real
        # authorization boundary — the same pair the bulk mark endpoints use.
        user = self._get_user()
        return get_object_or_404(
            NotificationEvent.objects.filter(  # nosemgrep: idor-lookup-without-team
                organization_id=self.team.organization_id,
                resolved_user_ids__contains=[user.id],
            ),
            pk=self.kwargs["pk"],  # nosemgrep: idor-taint-user-input-to-model-get
        )

    def _eligible_ids(self, ids: Sequence[UUID]) -> tuple[UUID, ...]:
        # NotificationEvent is org-scoped + user-targeted (notifications can span teams within an org),
        # not team-scoped. The (organization_id, resolved_user_ids__contains=[user.id]) pair already
        # ensures the caller can only touch notifications they were a recipient of — adding team_id
        # would silently drop notifications addressed to this user but with a different team_id.
        return tuple(
            NotificationEvent.objects.filter(  # nosemgrep: idor-lookup-without-team
                id__in=ids,  # nosemgrep: idor-taint-user-input-to-model-get
                organization_id=self.team.organization_id,
                resolved_user_ids__contains=[self._get_user().id],
            ).values_list("id", flat=True)
        )

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_read")
    def mark_read(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        event = self._get_recipient_event_or_404()
        NotificationReadState.objects.get_or_create(notification_event=event, user=user)
        invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"status": "ok"})

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="mark_unread")
    def mark_unread(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        event = self._get_recipient_event_or_404()
        NotificationReadState.objects.filter(notification_event=event, user=user).delete()
        invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"status": "ok"})

    @validated_request(request_serializer=BulkNotificationIdsRequestSerializer)
    @action(methods=["POST"], detail=False, url_path="mark_read_bulk")
    def mark_read_bulk(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"updated": 0})

        user = self._get_user()
        ids = request.validated_data["notification_ids"]
        if not ids:
            return Response({"updated": 0})

        eligible_ids = self._eligible_ids(ids)
        if eligible_ids:
            read_states = [NotificationReadState(notification_event_id=eid, user=user) for eid in eligible_ids]
            NotificationReadState.objects.bulk_create(read_states, ignore_conflicts=True)
            invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"updated": len(eligible_ids)})

    @validated_request(request_serializer=BulkNotificationIdsRequestSerializer)
    @action(methods=["POST"], detail=False, url_path="mark_unread_bulk")
    def mark_unread_bulk(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"updated": 0})

        user = self._get_user()
        ids = request.validated_data["notification_ids"]
        if not ids:
            return Response({"updated": 0})

        eligible_ids = self._eligible_ids(ids)
        if eligible_ids:
            NotificationReadState.objects.filter(
                notification_event_id__in=eligible_ids,
                user=user,
            ).delete()
            invalidate_unread_count(user.id, self.team.organization_id)
        return Response({"updated": len(eligible_ids)})

    # `Sequence`, not `list`: the viewset defines a `list` action, which shadows the builtin
    # when this annotation is evaluated in the class body.
    def _archive_events(self, user: User, event_ids: Sequence[UUID]) -> None:
        # Archiving takes a notification out of the unread count, so the read state has to follow.
        # Read and archive are independent tables, so without this an archived notification keeps
        # `read: false` and the archived list shows it as unread.
        with transaction.atomic():
            NotificationArchiveState.objects.bulk_create(
                [NotificationArchiveState(notification_event_id=eid, user=user) for eid in event_ids],
                ignore_conflicts=True,
            )
            NotificationReadState.objects.bulk_create(
                [NotificationReadState(notification_event_id=eid, user=user) for eid in event_ids],
                ignore_conflicts=True,
            )
        invalidate_unread_count(user.id, self.team.organization_id)

    def _unarchive_events(self, user: User, event_ids: Sequence[UUID], mark_unread: bool) -> None:
        with transaction.atomic():
            NotificationArchiveState.objects.filter(notification_event_id__in=event_ids, user=user).delete()
            if mark_unread:
                NotificationReadState.objects.filter(notification_event_id__in=event_ids, user=user).delete()
        invalidate_unread_count(user.id, self.team.organization_id)

    @extend_schema(request=None)
    @action(methods=["POST"], detail=True, url_path="archive")
    def archive(self, request: Request, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"status": "ok"})

        user = self._get_user()
        event = self._get_recipient_event_or_404()
        self._archive_events(user, [event.id])
        return Response({"status": "ok"})

    @validated_request(request_serializer=BulkNotificationIdsRequestSerializer)
    @action(methods=["POST"], detail=False, url_path="archive_bulk")
    def archive_bulk(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response({"updated": 0})

        user = self._get_user()
        ids = request.validated_data["notification_ids"]
        if not ids:
            return Response({"updated": 0})

        eligible_ids = self._eligible_ids(ids)
        if eligible_ids:
            self._archive_events(user, eligible_ids)
        return Response({"updated": len(eligible_ids)})

    @validated_request(
        query_serializer=NotificationFiltersQuerySerializer,
        responses={200: OpenApiResponse(response=ArchiveAllResponseSerializer)},
    )
    @action(methods=["POST"], detail=False, url_path="archive_all")
    def archive_all(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response(ArchiveAllResponseSerializer({"updated": 0, "notification_ids": []}).data)

        user = self._get_user()
        event_ids = list(
            self._matching_events(request.validated_query_data, archived=False).values_list("id", flat=True)
        )
        if event_ids:
            self._archive_events(user, event_ids)
        return Response(ArchiveAllResponseSerializer({"updated": len(event_ids), "notification_ids": event_ids}).data)

    @validated_request(
        request_serializer=UnarchiveRequestSerializer,
        responses={200: OpenApiResponse(response=UpdatedCountSerializer)},
    )
    @action(methods=["POST"], detail=True, url_path="unarchive")
    def unarchive(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response(UpdatedCountSerializer({"updated": 0}).data)

        event = self._get_recipient_event_or_404()
        self._unarchive_events(self._get_user(), [event.id], request.validated_data["mark_unread"])
        return Response(UpdatedCountSerializer({"updated": 1}).data)

    @validated_request(
        request_serializer=BulkUnarchiveRequestSerializer,
        responses={200: OpenApiResponse(response=UpdatedCountSerializer)},
    )
    @action(methods=["POST"], detail=False, url_path="unarchive_bulk")
    def unarchive_bulk(self, request: ValidatedRequest, **kwargs) -> Response:
        if not self._is_feature_enabled():
            return Response(UpdatedCountSerializer({"updated": 0}).data)

        eligible_ids = self._eligible_ids(request.validated_data["notification_ids"])
        if eligible_ids:
            self._unarchive_events(self._get_user(), eligible_ids, request.validated_data["mark_unread"])
        return Response(UpdatedCountSerializer({"updated": len(eligible_ids)}).data)
