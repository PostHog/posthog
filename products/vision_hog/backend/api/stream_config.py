from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.decorators import action

from posthog.hogql.ai import hit_open_ai_structured_output
from pydantic import BaseModel
from rest_framework import serializers
from posthog.models import StreamConfig


class EventSuggestions(BaseModel):
    event_suggestions: list[str]


SYSTEM_PROMPT = """
You are a helpful assistant that generates event suggestions for a stream.
The event should be a single word or phrase connected by underscores.
Create 2-3 event suggestions.

Example events:
- picked_up_coffee
- walked_into_store
- scanned_product
- added_to_cart
- completed_purchase
"""


class StreamConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreamConfig
        fields = ["id", "team_id", "stream_url", "events"]


class StreamConfigViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    serializer_class = StreamConfigSerializer
    queryset = StreamConfig.objects.all()

    @action(detail=False, methods=["POST"])
    def config_suggestion(self, request: Request, *args, **kwargs) -> Response:
        prompt = request.data.get("prompt")
        if not prompt:
            return Response({"error": "prompt is required"}, status=400)

        schema = hit_open_ai_structured_output(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            user=str(request.user.id),
            response_type=EventSuggestions,
        )

        return Response({"suggestions": list(schema.event_suggestions)})
