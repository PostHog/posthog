from typing import Final
from uuid import UUID

from pydantic import JsonValue

from products.cdp.backend.facade.api import disable_managed_hog_functions, upsert_managed_hog_function
from products.mcp_events.backend.facade.contracts import MCP_EVENT_NAME
from products.mcp_events.backend.logic.properties import MCPEventPropertyAccess
from products.mcp_events.backend.models import MCPEventSubscription

MANAGED_BY: Final = "mcp_events"
MAX_EVENT_BYTES: Final = 256 * 1024

# Hog has no way to delete a key, so the redacted properties are copied into a new dict.
DESTINATION_HOG: Final = """
if (toUnixTimestampMilli(now()) >= inputs.expires_at) {
  throw Error('The subscription has expired.')
}
let envelope := inputs.envelope
let redaction := inputs.restricted_properties
let source := envelope.data.properties
let properties := {}
if (typeof(source) == 'object') {
  for (let key, value in source) {
    let dropped := has(redaction.names, key)
    for (let prefix in redaction.prefixes) {
      if (startsWith(key, prefix)) {
        dropped := true
      }
    }
    let hiddenChildren := redaction.children[key]
    let hiddenItems := redaction.items[key]
    if (not dropped and not empty(hiddenChildren)) {
      if (typeof(value) == 'object') {
        let keptEntries := {}
        for (let childKey, childValue in value) {
          let normalizedChild := replaceAll(childKey, '%2E', '.')
          let hidden := false
          for (let hiddenChild in hiddenChildren) {
            if (normalizedChild == hiddenChild or
                startsWith(normalizedChild, f'{hiddenChild}.') or
                startsWith(hiddenChild, f'{normalizedChild}.')) {
              hidden := true
            }
          }
          if (not hidden) {
            keptEntries[childKey] := childValue
          }
        }
        properties[key] := keptEntries
      }
    } else if (not dropped and not empty(hiddenItems)) {
      if (typeof(value) == 'array') {
        let keptItems := []
        for (let item in value) {
          if (not has(hiddenItems, item)) {
            keptItems := arrayPushBack(keptItems, item)
          }
        }
        properties[key] := keptItems
      }
    } else if (not dropped) {
      properties[key] := value
    }
  }
}
let body := jsonStringify({
  'eventId': envelope.eventId,
  'name': envelope.name,
  'timestamp': envelope.timestamp,
  'data': {
    'event': envelope.data.event,
    'distinct_id': envelope.data.distinct_id,
    'properties': properties
  },
  'cursor': null
})
let encodedBody := base64Encode(body)
let padding := length(encodedBody) - length(trimRight(encodedBody, '='))
let byteLength := length(encodedBody) / 4 * 3 - padding
if (byteLength > inputs.max_bytes) {
  throw Error(f'The event exceeds the {inputs.max_bytes} byte delivery limit.')
}
let res := fetch(inputs.url, {
  'method': 'POST',
  'headers': {
    'Content-Type': 'application/json',
    'X-MCP-Subscription-Id': inputs.subscription_id
  },
  'body': body,
  'expires_at': inputs.expires_at,
  'standard_webhooks': {
    'secret_input': 'signing_secret'
  }
})
if (res.status >= 400) {
  throw Error(f'The MCP client rejected the event with status {res.status}.')
}
"""

ENVELOPE_TEMPLATE: Final[dict[str, JsonValue]] = {
    "eventId": "{event.uuid}",
    "name": MCP_EVENT_NAME,
    "timestamp": "{event.timestamp}",
    "data": {
        "event": "{event.event}",
        "distinct_id": "{event.distinct_id}",
        "properties": "{event.properties}",
    },
}


def _input_schema(key: str, input_type: str, label: str, *, secret: bool = False) -> dict[str, JsonValue]:
    return {"key": key, "type": input_type, "label": label, "secret": secret, "required": True, "templating": False}


def destination_payload(subscription: MCPEventSubscription) -> dict[str, JsonValue]:
    return {
        "name": "MCP event subscription",
        "description": "Sends matching captured events to the subscribing MCP client.",
        "template_id": None,
        "type": "destination",
        "enabled": True,
        "hog": DESTINATION_HOG,
        "inputs_schema": [
            _input_schema("url", "string", "Callback URL", secret=True),
            _input_schema("signing_secret", "string", "Signing secret", secret=True),
            _input_schema("subscription_id", "string", "Subscription ID"),
            _input_schema("restricted_properties", "json", "Hidden event properties"),
            _input_schema("max_bytes", "number", "Maximum event size in bytes"),
            _input_schema("expires_at", "number", "Delivery deadline in Unix milliseconds"),
            {"key": "envelope", "type": "json", "label": "Event envelope", "required": True},
        ],
        "filters": subscription.arguments["filters"],
        "inputs": {
            "url": {"value": subscription.delivery["url"]},
            "signing_secret": {"value": subscription.delivery["secret"]},
            "subscription_id": {"value": str(subscription.pk)},
            "restricted_properties": {"value": MCPEventPropertyAccess.redaction(subscription.restricted_properties)},
            "max_bytes": {"value": MAX_EVENT_BYTES},
            "expires_at": {"value": int(subscription.expires_at.timestamp() * 1000)},
            "envelope": {"value": ENVELOPE_TEMPLATE},
        },
    }


def save_destination(subscription: MCPEventSubscription) -> UUID:
    return upsert_managed_hog_function(
        destination_payload(subscription),
        team_id=subscription.team_id,
        created_by_id=subscription.created_by_id,
        managed_by=MANAGED_BY,
        hog_function_id=subscription.hog_function_id,
    )


def disable_destination(subscription: MCPEventSubscription) -> None:
    if subscription.hog_function_id is not None:
        disable_managed_hog_functions(
            team_id=subscription.team_id, managed_by=MANAGED_BY, hog_function_ids=[subscription.hog_function_id]
        )
