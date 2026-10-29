from drf_spectacular.utils import extend_schema_field
from pydantic import JsonValue
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.cdp.backend.facade.api import HogFunctionFiltersSerializer
from products.mcp_events.backend.facade.api import MAX_TTL_MS, validate_mcp_callback_url, validate_mcp_signing_secret
from products.mcp_events.backend.facade.contracts import MCP_EVENT_NAME, MCPEventData, MCPEventEnvelope


class MCPEventFiltersSerializer(HogFunctionFiltersSerializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["source"] = serializers.CharField(
            required=False, default="events", help_text="Captured PostHog events. Use events."
        )
        for key in ("bytecode", "bytecode_error", "bytecode_contract", "transpiled", "data_warehouse"):
            fields.pop(key, None)
        descriptions = {
            "events": 'Captured event entries combined with OR. Example: [{"id": "survey sent", "type": "events", "properties": [{"key": "rating", "type": "event", "operator": "lt", "value": 3}]}].',
            "actions": 'Saved action entries combined with the event entries using OR. Example: [{"id": "123", "type": "actions"}].',
            "properties": 'Property conditions applied to all selected events. Example: [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}].',
            "filter_test_accounts": "Apply the project's existing test-account exclusions.",
        }
        for key, description in descriptions.items():
            fields[key].help_text = description
        return fields

    def to_internal_value(self, data: object) -> dict[str, JsonValue]:
        if not isinstance(data, dict):
            raise ValidationError("Send event filters as a JSON object.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ValidationError(
                dict.fromkeys(sorted(unknown), "This field is not supported in subscription filters.")
            )
        return super().to_internal_value(data)

    def validate_source(self, value: str) -> str:
        if value != "events":
            raise ValidationError("MCP subscriptions support captured events. Use events.")
        return value

    def validate(self, data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # The service validates live filters; cancellation must also accept filters for deleted actions.
        return data


class MCPEventArgumentsSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(min_value=1, help_text="Project whose captured events should be monitored.")
    filters = MCPEventFiltersSerializer(
        help_text="Normal real-time destination filters. Preview the filters before subscribing."
    )

    def validate_project_id(self, value: int) -> int:
        if value != self.context["get_team"]().pk:
            raise ValidationError("Use the project in this endpoint's URL.")
        return value


class MCPEventIdentityArgumentsSerializer(MCPEventArgumentsSerializer):
    filters = MCPEventFiltersSerializer(help_text="Original event filters, including filters for deleted resources.")


class MCPEventWebhookSerializer(serializers.Serializer):
    mode = serializers.CharField(help_text="Delivery mode. Use webhook.")
    url = serializers.URLField(max_length=4096, help_text="HTTPS callback supplied by the receiving MCP client.")
    secret = serializers.CharField(
        write_only=True, max_length=128, trim_whitespace=False, help_text="Client-supplied whsec_ signing secret."
    )

    def validate_mode(self, value: str) -> str:
        if value != "webhook":
            raise ValidationError("Use webhook delivery.")
        return value

    def validate_url(self, value: str) -> str:
        return validate_mcp_callback_url(value)

    def validate_secret(self, value: str) -> str:
        return validate_mcp_signing_secret(value)


class MCPEventSubscribeSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event type. Use posthog.event_captured.")
    arguments = MCPEventArgumentsSerializer(help_text="Project and event filters for this subscription.")
    delivery = MCPEventWebhookSerializer(help_text="Callback and signing information supplied by the client.")
    ttl_ms = serializers.IntegerField(
        min_value=1000,
        required=False,
        allow_null=True,
        default=MAX_TTL_MS,
        help_text="Requested lifetime in milliseconds. The server grants a finite lifetime of at most 24 hours.",
    )
    cursor = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Replay is unavailable. Use null to receive future events.",
    )

    def validate_name(self, value: str) -> str:
        if value != MCP_EVENT_NAME:
            raise ValidationError("Use posthog.event_captured.")
        return value

    def validate_cursor(self, value: str | None) -> str | None:
        if value is not None:
            raise ValidationError("This event does not support replay. Use null.")
        return value


class MCPEventUnsubscribeDeliverySerializer(serializers.Serializer):
    mode = serializers.CharField(help_text="Delivery mode. Use webhook.")
    url = serializers.URLField(max_length=4096, help_text="Original callback URL supplied when subscribing.")

    def validate_mode(self, value: str) -> str:
        if value != "webhook":
            raise ValidationError("Use webhook delivery.")
        return value

    def validate_url(self, value: str) -> str:
        return validate_mcp_callback_url(value)


class MCPEventUnsubscribeSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event type. Use posthog.event_captured.")
    arguments = MCPEventIdentityArgumentsSerializer(help_text="Original project and event filters.")
    delivery = MCPEventUnsubscribeDeliverySerializer(help_text="Original callback identity.")

    def validate_name(self, value: str) -> str:
        if value != MCP_EVENT_NAME:
            raise ValidationError("Use posthog.event_captured.")
        return value


class MCPEventSubscriptionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Subscription ID supplied to the receiving MCP client.")
    arguments = MCPEventArgumentsSerializer(read_only=True, help_text="Project and event filters.")
    callback_host = serializers.CharField(
        read_only=True, help_text="Callback hostname. Paths and signing secrets are hidden."
    )
    expires_at = serializers.DateTimeField(
        read_only=True, help_text="Time when this subscription stops delivering events."
    )
    active = serializers.BooleanField(read_only=True, help_text="Whether this subscription is enabled.")
    created_at = serializers.DateTimeField(read_only=True, help_text="Time when this subscription was created.")


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "nullable": True,
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "object", "additionalProperties": True},
                {"type": "array", "items": {}},
            ],
        },
    }
)
class MCPEventPropertiesField(serializers.JSONField):
    pass


class MCPEventDataSerializer(DataclassSerializer):
    properties = MCPEventPropertiesField(help_text="Event properties the subscriber is allowed to read.")

    class Meta:
        dataclass = MCPEventData
        extra_kwargs = {
            "event": {"help_text": "Original captured event name.", "allow_blank": True},
            "distinct_id": {"help_text": "Distinct ID attached to the captured event.", "allow_blank": True},
        }


class MCPEventEnvelopeSerializer(DataclassSerializer):
    timestamp = serializers.DateTimeField(help_text="Event occurrence time, including its timezone.")
    cursor = serializers.JSONField(allow_null=True, help_text="Null because replay is unavailable.")

    class Meta:
        dataclass = MCPEventEnvelope
        extra_kwargs = {
            "eventId": {
                "min_length": 1,
                "max_length": 255,
                "help_text": "Stable source event ID used to deduplicate deliveries.",
            },
            "name": {"help_text": "Subscribed MCP event type."},
        }

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["data"] = MCPEventDataSerializer(help_text="Captured event data.")
        return fields


class MCPEventPreviewSerializer(serializers.Serializer):
    filters = MCPEventFiltersSerializer(read_only=True, help_text="Normalized filters the subscription would use.")
    examples = MCPEventEnvelopeSerializer(many=True, help_text="Up to five matching events from the lookback window.")
    lookback_days = serializers.IntegerField(help_text="Number of days searched for examples.")
    sample_limit = serializers.IntegerField(help_text="Maximum number of examples. This is not a total event count.")


class MCPEventEmptySerializer(serializers.Serializer):
    pass
