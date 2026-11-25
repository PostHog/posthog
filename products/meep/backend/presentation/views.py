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
        detail["context"] = api.topic_context(self.team_id, request.user.pk, pk, self._conversation(request))
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
