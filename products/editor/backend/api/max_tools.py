from typing import cast

import pydantic
from uuid import uuid4
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet
from rest_framework.permissions import IsAuthenticated

from ee.hogai.assistant import Assistant
from ee.hogai.utils.types import AssistantMode, AssistantState
from ee.models.assistant import Conversation
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.user import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer
from products.editor.backend.api.proxy import ServerSentEventRenderer


class InsightsToolCallSerializer(serializers.Serializer):
    query = serializers.CharField(required=True, max_length=1000)
    insight_type = serializers.ChoiceField(choices=["trends", "funnel", "retention", "sql"])

    def validate(self, data):
        try:
            tool_call_state = AssistantState(
                root_tool_call_id=str(uuid4()),
                root_tool_insight_plan=data["query"],
                root_tool_insight_type=data["insight_type"],
                messages=[],
            )
            data["state"] = tool_call_state
        except pydantic.ValidationError:
            raise serializers.ValidationError("Invalid state content.")
        return data


class MaxToolsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "project"
    queryset = Conversation.objects.all()

    permission_classes = [IsAuthenticated]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    authentication_classes = [PersonalAPIKeyAuthentication]

    @action(detail=False, methods=["POST"], url_path="create_and_query_insight", required_scopes=["insight:read"])
    def create_and_query_insight(self, request: Request, *args, **kwargs):
        serializer = InsightsToolCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = self.get_queryset().create(user=request.user, team=self.team, type=Conversation.Type.TOOL_CALL)
        assistant = Assistant(
            self.team,
            conversation,
            user=cast(User, request.user),
            is_new_conversation=False,  # we don't care about the conversation id being sent back to the client
            mode=AssistantMode.INSIGHTS_TOOL,
            tool_call_partial_state=serializer.validated_data["state"],
        )
        return StreamingHttpResponse(assistant.stream(), content_type=ServerSentEventRenderer.media_type)
