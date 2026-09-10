from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-gitea",
    name="Gitea warehouse source webhook",
    description="Receive Gitea webhook events for data warehouse ingestion",
    icon_url="/static/services/gitea.png",
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

if (not inputs.bypass_signature_check) {
  if (empty(inputs.signing_secret)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Signing secret not configured',
      }
    }
  }

  let signatureHeader := request.headers['x-gitea-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // Gitea sends the bare hex HMAC-SHA256 of the raw request body keyed by the
  // webhook secret (no sha256= prefix, unlike GitHub).
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, request.stringBody])

  if (computedSignature != signatureHeader) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

// Event type comes from the X-Gitea-Event header, not the body.
let eventType := request.headers['x-gitea-event']

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[eventType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventType}, skipping'
    }
  }
}

// The poll endpoints land the issue/pull_request objects themselves, so the webhook
// lands the same nested object. Gitea serializes one struct per resource, so the
// nested webhook object matches the REST list response shape. The 'issues' event
// nests its object under the singular 'issue' key; other events use the event name.
let bodyKey := eventType
if (eventType = 'issues') {
  bodyKey := 'issue'
}

let row := request.body?.[bodyKey]

if (empty(row)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No {bodyKey} object in payload, skipping'
    }
  }
}

produceToWarehouseWebhooks(row, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from your Gitea instance. Set as the webhook's Secret in the repo's Settings > Webhooks.",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-Gitea-Signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Gitea event types (issues, pull_request) to ExternalDataSchema IDs",
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
