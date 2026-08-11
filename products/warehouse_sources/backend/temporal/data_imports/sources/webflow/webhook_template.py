from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-webflow",
    name="Webflow warehouse source webhook",
    description="Receive Webflow webhook events for data warehouse ingestion",
    icon_url="/static/services/webflow.png",
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

let timestamp := request.headers['x-webflow-timestamp']

if (not inputs.bypass_signature_check) {
  let signature := request.headers['x-webflow-signature']

  if (empty(timestamp) or empty(signature)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  // Webflow registers one webhook per trigger type and issues each its own secret, so a
  // delivery can be signed by any of the secrets handed back when we registered them.
  // The manually-entered secret is appended for sites set up by hand.
  let secrets := []
  if (not empty(inputs.signing_secrets)) {
    secrets := inputs.signing_secrets
  }
  if (not empty(inputs.signing_secret)) {
    secrets := arrayPushBack(secrets, inputs.signing_secret)
  }

  if (empty(secrets)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Signing secret not configured',
      }
    }
  }

  // Webflow signs `<timestamp>:<raw body>` with HMAC-SHA256, hex encoded.
  let signedPayload := concat(timestamp, ':', request.stringBody)
  let signatureValid := false

  for (let _, secret in secrets) {
    if (sha256HmacChainHex([secret, signedPayload]) = signature) {
      signatureValid := true
    }
  }

  if (not signatureValid) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }

  // The signature covers the timestamp, so a captured delivery stays valid forever unless we
  // bound its age. Webflow's timestamp is Unix epoch milliseconds and their guidance is to
  // treat anything older than five minutes as compromised.
  if (toUnixTimestampMilli(now()) - toInt(timestamp) > 300000) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Stale delivery',
      }
    }
  }
}

let triggerType := request.body.triggerType

if (empty(triggerType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No trigger type found, skipping'
    }
  }
}

// Several trigger types feed one warehouse table, so the trigger is collapsed to a resource
// key before the schema lookup. Keep in sync with WEBHOOK_EVENT_TO_RESOURCE in settings.py.
let resourceByTrigger := {
  'ecomm_new_order': 'orders',
  'ecomm_order_changed': 'orders',
}

let resource := resourceByTrigger?.[triggerType]

if (empty(resource)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'Unhandled trigger type: {triggerType}, skipping'
    }
  }
}

let schemaId := inputs.schema_mapping?.[resource]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for trigger type: {triggerType}, skipping'
    }
  }
}

// The delivery timestamp is kept alongside the resource so the loader can tell which of two
// events for the same object is the newer one. Webflow puts no timestamp in the body.
produceToWarehouseWebhooks(
  {
    'triggerType': triggerType,
    'webflowTimestamp': timestamp,
    'payload': request.body.payload,
  },
  schemaId
)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "A webhook's secret key from Webflow. Used to verify the x-webflow-signature header "
                "(HMAC-SHA256 of `<x-webflow-timestamp>:<raw body>`) so deliveries provably come from Webflow."
            ),
        },
        {
            "type": "json",
            "key": "signing_secrets",
            "label": "Signing secrets",
            "description": ("Secret keys Webflow returned when PostHog registered the webhooks. One per trigger type."),
            "default": [],
            "required": False,
            "secret": True,
            "hidden": True,
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the x-webflow-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Webflow resources to ExternalDataSchema IDs",
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
