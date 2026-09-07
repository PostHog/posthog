from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Whop follows the Standard Webhooks spec: `webhook-id`, `webhook-timestamp` (Unix seconds) and
# `webhook-signature` (a space-separated list of `v<version>,<base64 HMAC-SHA256>` entries) signing
# "{id}.{timestamp}.{raw body}". Whop's own SDK snippets base64-encode the dashboard secret before
# handing it to the verifier, which decodes it straight back, so the HMAC key is the secret string
# exactly as Whop displays it.
#
# The payload envelope is {id, type, timestamp, company_id, data}; `type` is `<resource>.<action>`
# (e.g. `payment.succeeded`), so the resource prefix is the schema routing key.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-whop",
    name="Whop warehouse source webhook",
    description="Receive Whop webhook events for data warehouse ingestion",
    icon_url="/static/services/whop.png",
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

  let webhookId := request.headers['webhook-id']
  let timestamp := request.headers['webhook-timestamp']
  let signatureHeader := request.headers['webhook-signature']

  if (empty(webhookId) or empty(timestamp) or empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let signedPayload := concat(webhookId, '.', timestamp, '.', request.stringBody)
  let computedSignature := sha256HmacChain([inputs.signing_secret, signedPayload], 'base64')

  // The header can carry several `v1,<signature>` entries, so match on containment rather than
  // equality; the signature is base64 and long enough that a substring hit is the real one.
  if (position(signatureHeader, computedSignature) == 0) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }

  let timestampDelta := toInt(toUnixTimestamp(now())) - toInt(timestamp)
  if (timestampDelta > 300 or timestampDelta < -300) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Timestamp outside tolerance',
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

let resourceType := splitByString('.', eventType)[1]
let schemaId := inputs.schema_mapping?.[resourceType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for resource type: {resourceType}, skipping'
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
                "The webhook's signing secret from Whop. Used to verify the webhook-signature header "
                "so deliveries provably come from Whop."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the webhook-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Whop resource types to ExternalDataSchema IDs",
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
