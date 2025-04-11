from typing import cast

import pydantic
import json
from uuid import uuid4
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.permissions import IsAuthenticated

from ee.hogai.assistant import Assistant
from ee.hogai.utils.types import AssistantMode, PartialAssistantState
from ee.models.assistant import Conversation
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.schema import HumanMessage


class BaseMaxToolsSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(required=True)


class InsightsToolCallSerializer(BaseMaxToolsSerializer):
    query_description = serializers.CharField(required=True, max_length=1000)
    query_type = serializers.ChoiceField(choices=["trends", "funnel", "retention", "sql"])

    def validate(self, data):
        try:
            tool_call_state = PartialAssistantState(
                root_tool_call_id=str(uuid4()),
                root_tool_insight_plan=data["query_description"],
                root_tool_insight_type=data["query_type"],
            )
            data["state"] = tool_call_state
        except pydantic.ValidationError:
            raise serializers.ValidationError("Invalid state content.")
        return data


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, dict | list):
            return None
        return data


class JSONRenderer(BaseRenderer):
    media_type = "application/json"
    format = "json"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, dict | list):
            return json.dumps(data).encode()
        return None


class MaxToolsViewSet(GenericViewSet):
    queryset = Conversation.objects.all()
    lookup_url_kwarg = "conversation"

    authentication_classes = [PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, ServerSentEventRenderer]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]

    @action(detail=False, methods=["POST"], url_path="insights")
    def insights_tool_call(self, request: Request, *args, **kwargs):
        serializer = InsightsToolCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project_id = serializer.validated_data["project_id"]
        try:
            self.team = Team.objects.get(id=project_id)
        except Team.DoesNotExist:
            raise serializers.ValidationError("Team does not exist")
        conversation = self.get_queryset().create(user=request.user, team=self.team, type=Conversation.Type.TOOL_CALL)
        assistant = Assistant(
            self.team,
            conversation,
            new_message=HumanMessage(content=serializer.validated_data["state"].root_tool_insight_plan),
            user=cast(User, request.user),
            is_new_conversation=False,  # we don't care about the conversation id being sent back to the client
            mode=AssistantMode.INSIGHTS_TOOL,
            tool_call_partial_state=serializer.validated_data["state"],
        )
        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)
