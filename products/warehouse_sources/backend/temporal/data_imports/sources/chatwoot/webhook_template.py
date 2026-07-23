from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Chatwoot signs deliveries (recent versions) with X-Chatwoot-Signature: sha256=<hex hmac-sha256 of
# "<X-Chatwoot-Timestamp>.<raw body>">. Older self-hosted installs have no per-webhook secret and
# deliver unsigned — those users must enable bypass_signature_check explicitly.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-chatwoot",
    name="Chatwoot warehouse source webhook",
    description="Receive Chatwoot webhook events for data warehouse ingestion",
    icon_url="/static/services/chatwoot.png",
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

  let body := request.stringBody
  let signatureHeader := request.headers['x-chatwoot-signature']
  let timestamp := request.headers['x-chatwoot-timestamp']

  if (empty(signatureHeader) or empty(timestamp)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  if (not (signatureHeader like 'sha256=%')) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Could not parse signature',
      }
    }
  }

  let sigParts := splitByString('sha256=', signatureHeader, 2)
  let providedSignature := sigParts[2]

  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])

  if (computedSignature != providedSignature) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }

  let currentTime := toInt(toUnixTimestamp(now()))
  let timestampDelta := currentTime - toInt(timestamp)
  if (timestampDelta > 300 or timestampDelta < -300) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Timestamp outside tolerance',
        }
      }
  }
}

let event := request.body.event

if (empty(event)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event found, skipping'
    }
  }
}

// The event name prefix is the object type: message_created -> message,
// conversation_status_changed -> conversation.
let objectType := splitByString('_', event)[1]

let schemaId := inputs.schema_mapping?.[objectType]

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for object type: {objectType}, skipping'
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
            "description": "Used to validate the webhook came from Chatwoot",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the x-chatwoot-signature header will not be checked. Only use this for older self-hosted Chatwoot versions that do not sign webhook deliveries.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps Chatwoot object types to ExternalDataSchema IDs",
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
