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
import requests
import logging
import json
from typing import cast

logger = logging.getLogger(__name__)


class EventPropertyConfig(BaseModel):
    name: str
    description: str


class EventConfig(BaseModel):
    name: str
    description: str
    properties: list[EventPropertyConfig]


class EventSuggestions(BaseModel):
    event_suggestions: list[EventConfig]


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

    def _generate_analysis_prompt(self, events: list[EventConfig]) -> str:
        """Construct a prompt for the LLM that

        1. Describes the allowed events and their properties using the strongly-typed ``EventConfig`` model.
        2. Provides **one example JSON object per event type** that includes the default PostHog properties plus the
           custom properties the user defined for that event.

        The function is tolerant to receiving either raw dicts (the request payload) or fully-fledged ``EventConfig``
        instances. It converts everything to ``EventConfig`` so we can rely on attribute access instead of subscripting.
        """

        # Normalise the input so that we always deal with EventConfig objects
        normalised_events: list[EventConfig] = []
        for evt in events or []:
            if isinstance(evt, EventConfig):
                normalised_events.append(evt)
            else:
                # Assume ``evt`` is a mapping/dict coming from the API payload
                normalised_events.append(EventConfig.parse_obj(evt))

        # ---------------------------------------------------------------------
        # 1. Human-readable description of the events we care about
        # ---------------------------------------------------------------------
        event_examples: list[str] = []
        event_names_for_prompt: list[str] = []
        for event in normalised_events:
            event_text = f"{event.name} ({event.description})"
            if event.properties:
                props = ", ".join([f"{prop.name} ({prop.description})" for prop in event.properties])
                event_text += f" with properties: {props}"
            event_examples.append(event_text)
            event_names_for_prompt.append(event.name)

        event_examples_str = ", ".join(event_examples)

        # ---------------------------------------------------------------------
        # 2. Ask the LLM for example JSON – **only** the examples, not the prompt.
        # ---------------------------------------------------------------------
        from pydantic import BaseModel
        from typing import Any
        from posthog.hogql.ai import hit_open_ai_structured_output

        class ExampleEvent(BaseModel):
            event: str
            properties: dict[str, Any]

        class ExampleEventsResponse(BaseModel):
            examples: list[ExampleEvent]

        GENERATE_EXAMPLE_EVENTS_SYSTEM_PROMPT = """
You are a helpful assistant that produces example PostHog event payloads. Given a list of events definitions, output a JSON
array where each item corresponds to a distinct event. Each item must include:

- "event": the event name exactly as provided.
- "properties": an object containing at minimum the following keys:
  - "timestamp": string in HH:MM:SS format
  - "distinct_id": string beginning with "camera:"
  - "description": short text describing the interaction
  - "duration_seconds": number (integer)
  - "interaction_type": string

Add any custom properties supplied in the event definition. If a property name is provided, include it with an example
value. Values can be simple placeholders (e.g., "example_<property>").

Return ONLY the JSON array, no markdown, code fences or additional commentary.
"""

        # Build user prompt describing the events for the LLM
        events_description_for_llm: list[str] = []
        for event in normalised_events:
            custom_props = ", ".join(p.name for p in (event.properties or [])) or "no custom props"
            events_description_for_llm.append(f"- {event.name}: {event.description} (custom props: {custom_props})")

        user_prompt_examples = "Generate example JSON for these events:\n" + "\n".join(events_description_for_llm)

        example_json_str: str
        try:
            schema = cast(
                ExampleEventsResponse,
                hit_open_ai_structured_output(
                    messages=[
                        {"role": "system", "content": GENERATE_EXAMPLE_EVENTS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt_examples},
                    ],
                    # Use a generic identifier if serializer context doesn't have a user
                    user=str(getattr(self.context.get("request", None), "user", "system")),
                    response_type=ExampleEventsResponse,
                ),
            )

            example_json_str = json.dumps([event.dict() for event in schema.examples], indent=2)
        except Exception:  # noqa: BLE001
            # Fallback: deterministic example generation similar to previous logic
            example_events_json = []
            for idx, event in enumerate(normalised_events, start=1):
                fallback_props: dict[str, str | int] = {
                    "timestamp": "00:00:15",
                    "distinct_id": f"camera:customer_{idx}",
                    "description": event.description,
                    "duration_seconds": 5,
                    "interaction_type": "interaction_type_example",
                }
                for prop_def in event.properties or []:
                    fallback_props[prop_def.name] = f"example_{prop_def.name}"

                example_events_json.append({"event": event.name, "properties": fallback_props})

            example_json_str = json.dumps(example_events_json, indent=2)

        # ---------------------------------------------------------------------
        # 3. Construct the final prompt string
        # ---------------------------------------------------------------------
        base_prompt = f"""Analyze this video of the environment and identify key customer events and interactions.
For each event, provide a description and its approximate timestamp in the video.
Return the output as a valid JSON array of objects that follows PostHog's event schema. Each object must have the following fields:

- "event": String - The specific customer action (e.g., {event_names_for_prompt})
- "properties": Object containing:
  - "timestamp": "HH:MM:SS" (String format for hours, minutes, seconds)
  - "distinct_id": String - A unique identifier for the customer, prefixed with "camera:" (e.g., "camera:customer_1", "camera:customer_2")
  - "description": String - A concise description of what the customer did
  - "duration_seconds": Number - Approximate duration of the activity in seconds
  - "interaction_type": String - Type of activity (e.g., "person_in_frame", "person_out_of_frame")
  - Any additional custom properties that are relevant to the event.

You can add more properties if you think they are relevant.

Example of expected JSON output (one object per event type):
{example_json_str}

Ensure the output is only the JSON array and nothing else.
If no specific events are identifiable, return an empty array []."""

        # Explicitly instruct the model to only track the specified events
        events_prompt = f"\n\nTrack *only* these specific events: {event_examples_str}" if normalised_events else ""

        return base_prompt + events_prompt

    def _save_prompt(self, prompt: str):
        try:
            response = requests.post(
                "http://127.0.0.1:8069/prompt", json={"prompt": prompt, "emit_events": True}, timeout=5
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to save prompt")

    def create(self, validated_data):
        team_id = self.context["team_id"]
        validated_data["team_id"] = team_id
        logger.info(f"Creating stream config with events: {validated_data['events']}")
        prompt = self._generate_analysis_prompt(validated_data["events"])
        self._save_prompt(prompt)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        logger.info(f"Updating stream config with events: {validated_data['events']}")
        prompt = self._generate_analysis_prompt(validated_data["events"])
        self._save_prompt(prompt)
        return super().update(instance, validated_data)


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
                {"role": "system", "content": GENERATE_EVENT_SUGGESTIONS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            user=str(request.user.id),
            response_type=EventSuggestions,
        )

        return Response({"suggestions": list(schema.event_suggestions)})
