from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Instantly does not sign webhook deliveries, but it does send static custom headers configured
# on the webhook. `create_webhook` attaches a generated secret in the x-posthog-webhook-secret
# header, which this template verifies. Manually created webhooks must configure the same header,
# or enable the bypass toggle.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-instantly",
    name="Instantly warehouse source webhook",
    description="Receive Instantly webhook events for data warehouse ingestion",
    icon_url="/static/services/instantly.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method != 'POST') {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
}

if (not inputs.bypass_secret_check) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Webhook secret not configured',
      }
    }
  }

  let providedSecret := request.headers['x-posthog-webhook-secret']

  if (empty(providedSecret) or providedSecret != inputs.signing_secret) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad webhook secret',
      }
    }
  }
}

let eventType := request.body.event_type

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event_type found, skipping'
    }
  }
}

// Every Instantly event (including custom label events) lands in the single
// webhook_events table.
let schemaId := inputs.schema_mapping?.['event']

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No schema mapping for events, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Webhook secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Shared secret sent by Instantly in the x-posthog-webhook-secret header, used to verify the delivery came from your webhook",
        },
        {
            "type": "boolean",
            "key": "bypass_secret_check",
            "label": "Bypass secret check",
            "description": "If set, the x-posthog-webhook-secret header will not be checked. Only use this for manually created webhooks without the secret header configured.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Instantly webhook events to ExternalDataSchema IDs",
            "required": True,
            "secret": False,
            "hidden": True,
        },
        {
            "type": "string",
            "key": "source_id",
            "label": "Source ID",
            "description": "The ExternalDataSource ID this webhook is associated with",
            "required": True,
            "secret": False,
            "hidden": True,
        },
    ],
)
