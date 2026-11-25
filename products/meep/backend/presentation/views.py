from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request

from products.meep.backend.facade import api
from products.meep.backend.presentation.scout_access import canonical_scout_access, show_scouts
from products.signals.backend.facade.source_scouts import cron_schedule_error


class MeepScoutCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    instructions = serializers.CharField(max_length=16000)
    cron = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Optional five-field schedule in the project's timezone. Defaults to the native scout cadence.",
    )

    def validate_cron(self, value: str) -> str:
        if error := cron_schedule_error(value):
            raise serializers.ValidationError(error)
        return value


class MeepScoutStatusSerializer(serializers.Serializer):
    scout_id = serializers.UUIDField()
    enabled = serializers.BooleanField()


class MeepScoutSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    skill_name = serializers.CharField()
    enabled = serializers.BooleanField()


class MeepConversationBindingSerializer(serializers.Serializer):
    task_id = serializers.UUIDField()


class MeepTopicSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(max_length=255)
    mission = serializers.CharField()
    conversation_id = serializers.UUIDField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class MeepTopicDetailsSerializer(MeepTopicSerializer):
    context = serializers.DictField(read_only=True)


class TopicViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "meep"
    permission_classes = [IsAuthenticated]
    serializer_class = MeepTopicSerializer
    path_parameters = {"pk": UUID}
    records_have_object_access_rules = False

    def _conversation(self, request: Request) -> UUID | None:
        if is_sandbox_oauth_request(request):
            key = getattr(get_oauth_access_token(request), "sandbox_task_id", None)
            if key is None:
                raise PermissionDenied("The task credential must identify its task.")
            return key
        return None

    def list(self, request: Request, **kwargs: Any) -> Response:
        topics = api.list_topics(self.team_id, request.user.pk, self._conversation(request))
        page = self.paginate_queryset(topics)
        if page is not None:
            return self.get_paginated_response(MeepTopicSerializer(page, many=True).data)
        return Response(MeepTopicSerializer(topics, many=True).data)

    @extend_schema(responses=MeepTopicDetailsSerializer)
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        topic = api.read_topic(self.team_id, request.user.pk, pk, self._conversation(request))
        detail = dict(MeepTopicSerializer(topic).data)
        detail["context"] = api.topic_context(
            self.team_id, request.user.pk, pk, self._conversation(request), include_scouts=show_scouts(self)
        )
        return Response(detail)

    def create(self, request: Request, **kwargs: Any) -> Response:
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Only a person can create a topic.")
        data = MeepTopicSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topic = api.create_topic(self.team_id, request.user.pk, **data.validated_data)
        return Response(MeepTopicSerializer(topic).data, status=201)

    @extend_schema(request=MeepConversationBindingSerializer, responses=MeepTopicSerializer)
    @action(methods=["post"], detail=True, required_scopes=["meep:write", "task:read"])
    def conversation(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Only a person can bind a task.")
        data = MeepConversationBindingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        topic = api.bind_conversation(self.team_id, request.user.pk, pk, data.validated_data["task_id"])
        return Response(MeepTopicSerializer(topic).data)

    @extend_schema(
        operation_id="meep_topics_create_scout",
        request=MeepScoutCreateSerializer,
        responses={200: MeepScoutSerializer, 201: MeepScoutSerializer},
    )
    @action(methods=["post"], detail=True, url_path="scouts", required_scopes=["meep_scout:write"])
    def create_scout(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        task_id = self._conversation(request)
        if task_id is None or not canonical_scout_access(self):
            raise PermissionDenied("Create this scout from its Meep topic in a project you can access.")
        payload = MeepScoutCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scout, created = api.create_topic_scout(
            team=self.team,
            user=request.user,
            task_id=task_id,
            topic_id=pk,
            name=payload.validated_data["name"],
            instructions=payload.validated_data["instructions"],
            cron=payload.validated_data.get("cron"),
            request=request,
        )
        return Response(MeepScoutSerializer(scout).data, status=201 if created else 200)

    @extend_schema(
        operation_id="meep_topics_set_scout_enabled", request=MeepScoutStatusSerializer, responses=MeepScoutSerializer
    )
    @action(methods=["post"], detail=True, url_path="scout-status", required_scopes=["meep_scout:write"])
    def scout_status(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        task_id = self._conversation(request)
        if task_id is None or not canonical_scout_access(self):
            raise PermissionDenied("Manage this scout from its Meep topic in a project you can access.")
        payload = MeepScoutStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scout = api.set_topic_scout_enabled(
            team=self.team,
            user=request.user,
            task_id=task_id,
            topic_id=pk,
            scout_id=payload.validated_data["scout_id"],
            enabled=payload.validated_data["enabled"],
            request=request,
        )
        return Response(MeepScoutSerializer(scout).data)
