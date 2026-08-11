from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-fourthwall",
    name="Fourthwall warehouse source webhook",
    description="Receive Fourthwall webhook events for data warehouse ingestion",
    icon_url="/static/services/fourthwall.png",
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

  let signature := request.headers['x-fourthwall-hmac-sha256']

  if (empty(signature)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // Fourthwall sends the base64-encoded HMAC-SHA256 of the raw request body, keyed by the
  // shop's webhook secret. No timestamp is involved.
  let computedSignature := sha256HmacChain([inputs.signing_secret, request.stringBody], 'base64')

  if (computedSignature != signature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

let eventType := request.body.type

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

// Several event types feed one warehouse table, so the event is collapsed to a resource key
// before the schema lookup. Keep this in sync with WEBHOOK_EVENT_TO_RESOURCE in settings.py.
let resourceByEvent := {
  'ORDER_PLACED': 'order',
  'ORDER_UPDATED': 'order',
  'DONATION': 'donation',
  'SUBSCRIPTION_PURCHASED': 'member',
  'SUBSCRIPTION_CHANGED': 'member',
  'SUBSCRIPTION_EXPIRED': 'member',
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

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "Your shop's webhook secret key. Used to verify the X-Fourthwall-Hmac-SHA256 header "
                "(base64 HMAC-SHA256 of the raw request body) so deliveries provably come from Fourthwall."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the X-Fourthwall-Hmac-SHA256 header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Fourthwall resource keys to ExternalDataSchema IDs",
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
