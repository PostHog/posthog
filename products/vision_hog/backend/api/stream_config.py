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


GENERATE_EVENT_SUGGESTIONS_SYSTEM_PROMPT = """
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

    def _generate_analysis_prompt(self, events: list[str]) -> str:
        base_prompt = f"""Analyze this video of a retail environment and identify key customer events and interactions.
For each event, provide a description and its approximate timestamp in the video.
Return the output as a valid JSON array of objects that follows PostHog's event schema. Each object must have the following fields:

- "event": String - The specific customer action (e.g., {', '.join(events)})
- "properties": Object containing:
  - "timestamp": "HH:MM:SS" (String format for hours, minutes, seconds)
  - "distinct_id": String - A unique identifier for the customer, prefixed with "camera_" (e.g., "camera_customer_1", "camera_customer_2")
  - "description": String - A concise description of what the customer did
  - "location": String - Area within the retail space
  - "duration_seconds": Number - Approximate duration of the activity in seconds
  - "interaction_type": String - Type of activity (e.g., "entry_exit", "product_engagement", "service_usage", "staff_interaction")

Example of expected JSON output:
[
  {
    "event": "{events[0]}",
    "properties": {
      "timestamp": "00:00:15",
      "distinct_id": "camera_customer_1",
      "description": "Customer enters through the main entrance",
      "location": "entrance",
      "duration_seconds": 5,
      "interaction_type": "entry_exit"
    }
  }
]

Ensure the output is only the JSON array and nothing else.
If no specific events are identifiable, return an empty array []."""

        # Add events from config to prompt
        events_prompt = f"\n\nTrack these specific events: {', '.join(events)}" if events else ""

        return base_prompt + events_prompt

    @action(detail=False, methods=["POST"])
    def config_suggestion(self, request: Request, *args, **kwargs) -> Response:
        prompt = request.data.get("prompt")
        if not prompt:
            return Response({"error": "prompt is required"}, status=400)

        schema = hit_open_ai_structured_output(
            messages=[
                {"role": "system", "content": GENERATE_EVENT_SUGGESTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            user=str(request.user.id),
            response_type=EventSuggestions,
        )

        return Response({"suggestions": list(schema.event_suggestions)})
