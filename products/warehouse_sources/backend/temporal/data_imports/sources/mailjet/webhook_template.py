from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-mailjet",
    name="Mailjet warehouse source webhook",
    description="Receive Mailjet Event API events for data warehouse ingestion",
    icon_url="/static/services/mailjet.png",
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

if (not inputs.bypass_authorization_check) {
  if (empty(inputs.authorization_header)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Authorization header value not configured',
      }
    }
  }

  // Mailjet signs nothing. It authenticates deliveries with the basic-auth credentials embedded
  // in the registered callback URL, which arrive here as an Authorization header.
  let providedHeader := request.headers['authorization']

  if (empty(providedHeader)) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Missing authorization header',
      }
    }
  }

  if (providedHeader != inputs.authorization_header) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Bad authorization header',
      }
    }
  }
}

// Version 1 callbacks post one event object. Version 2 posts an array of them, which the
// warehouse webhook pipeline can't unpack into rows — acknowledge and drop rather than error.
if (typeof(request.body) != 'object') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Expected a single event object, skipping'
    }
  }
}

let eventType := request.body?.event

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

// Every Mailjet event type feeds the one messageevent table. Keep this in sync with
// MAILJET_WEBHOOK_EVENTS and SCHEMA_TO_WEBHOOK_RESOURCE in settings.py.
let resourceByEvent := {
  'sent': 'messageevent',
  'open': 'messageevent',
  'click': 'messageevent',
  'bounce': 'messageevent',
  'blocked': 'messageevent',
  'spam': 'messageevent',
  'unsub': 'messageevent',
}

let resource := resourceByEvent?.[eventType]

if (empty(resource)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'Unhandled event type: {eventType}, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[resource]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventType}, skipping'
    }
  }
}

// Mailjet events carry no identifier of their own, so the raw body's hash is the row key.
// Mailjet re-POSTs the same body until it gets a 200, so retries land on the same row.
let row := request.body
row.event_id := sha256Hex(request.stringBody)

produceToWarehouseWebhooks(row, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "authorization_header",
            "label": "Authorization header",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "The Authorization header PostHog expects on every Mailjet delivery. PostHog generates it "
                "and registers the matching basic-auth credentials on the Mailjet callback URL."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_authorization_check",
            "label": "Bypass authorization check",
            "description": "If set, the Authorization header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Mailjet resource keys to ExternalDataSchema IDs",
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
